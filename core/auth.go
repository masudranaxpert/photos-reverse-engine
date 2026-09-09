package gpmc

import (
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// TokenManager handles exchanging the Android master token (AUTH_DATA) for OAuth2 Bearer tokens.
type TokenManager struct {
	authData string
	params   url.Values

	mu          sync.RWMutex
	cachedToken string
	expiresAt   time.Time

	httpClient *http.Client
}

// NewTokenManager parses AUTH_DATA and initializes the token manager.
func NewTokenManager(authData string) (*TokenManager, error) {
	cleanAuth := strings.TrimSpace(authData)
	cleanAuth = strings.Trim(cleanAuth, "'\"")
	if cleanAuth == "" {
		return nil, fmt.Errorf("AUTH_DATA cannot be empty")
	}

	values, err := url.ParseQuery(cleanAuth)
	if err != nil {
		return nil, fmt.Errorf("failed to parse AUTH_DATA: %w", err)
	}

	return &TokenManager{
		authData: cleanAuth,
		params:   values,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}, nil
}

// GetToken returns a valid OAuth2 Bearer token, refreshing it proactively if needed.
func (tm *TokenManager) GetToken(ctx context.Context) (string, error) {
	tm.mu.RLock()
	// Refresh 5 minutes before actual expiry
	if tm.cachedToken != "" && time.Now().Add(5*time.Minute).Before(tm.expiresAt) {
		token := tm.cachedToken
		tm.mu.RUnlock()
		return token, nil
	}
	tm.mu.RUnlock()

	tm.mu.Lock()
	defer tm.mu.Unlock()

	// Double-check after acquiring write lock
	if tm.cachedToken != "" && time.Now().Add(5*time.Minute).Before(tm.expiresAt) {
		return tm.cachedToken, nil
	}

	return tm.fetchTokenLocked(ctx)
}

// Invalidate clears the cached token to force a refresh on next access.
func (tm *TokenManager) Invalidate() {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	tm.cachedToken = ""
	tm.expiresAt = time.Time{}
}

func (tm *TokenManager) fetchTokenLocked(ctx context.Context) (string, error) {
	getParam := func(k, fallback string) string {
		if v := tm.params.Get(k); v != "" {
			return v
		}
		return fallback
	}

	androidID := getParam("androidId", "")
	if androidID == "" {
		return "", fmt.Errorf("androidId not found in AUTH_DATA")
	}

	formData := url.Values{
		"androidId":                    {androidID},
		"app":                          {"com.google.android.apps.photos"},
		"client_sig":                   {getParam("client_sig", "")},
		"callerPkg":                    {"com.google.android.apps.photos"},
		"callerSig":                    {getParam("callerSig", "")},
		"device_country":               {getParam("device_country", "us")},
		"Email":                        {getParam("Email", "")},
		"google_play_services_version": {getParam("google_play_services_version", "250932000")},
		"lang":                         {getParam("lang", "en_US")},
		"oauth2_foreground":            {getParam("oauth2_foreground", "1")},
		"sdk_version":                  {getParam("sdk_version", "28")},
		"service":                      {getParam("service", "")},
		"Token":                        {getParam("Token", "")},
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://android.googleapis.com/auth", strings.NewReader(formData.Encode()))
	if err != nil {
		return "", fmt.Errorf("failed to create auth request: %w", err)
	}

	req.Header.Set("Accept-Encoding", "gzip")
	req.Header.Set("app", "com.google.android.apps.photos")
	req.Header.Set("Connection", "Keep-Alive")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("device", androidID)
	req.Header.Set("User-Agent", "GoogleAuth/1.4 (Pixel XL PQ2A.190205.001); gzip")

	resp, err := tm.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("auth request failed: %w", err)
	}
	defer resp.Body.Close()

	var reader io.Reader = resp.Body
	if strings.EqualFold(resp.Header.Get("Content-Encoding"), "gzip") {
		gz, err := gzip.NewReader(resp.Body)
		if err != nil {
			return "", fmt.Errorf("failed to create gzip reader: %w", err)
		}
		defer gz.Close()
		reader = gz
	}

	bodyBytes, err := io.ReadAll(reader)
	if err != nil {
		return "", fmt.Errorf("failed to read auth response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("auth endpoint returned status %d: %s", resp.StatusCode, string(bodyBytes))
	}

	parsed := make(map[string]string)
	for _, line := range strings.Split(string(bodyBytes), "\n") {
		line = strings.TrimSpace(line)
		if idx := strings.Index(line, "="); idx != -1 {
			parsed[line[:idx]] = line[idx+1:]
		}
	}

	authToken, ok := parsed["Auth"]
	if !ok || authToken == "" {
		return "", fmt.Errorf("auth token not found in response: %v", parsed)
	}

	tm.cachedToken = authToken
	if expiryStr, ok := parsed["Expiry"]; ok {
		if expInt, err := strconv.ParseInt(expiryStr, 10, 64); err == nil {
			tm.expiresAt = time.Unix(expInt, 0)
		} else {
			tm.expiresAt = time.Now().Add(50 * time.Minute)
		}
	} else {
		tm.expiresAt = time.Now().Add(50 * time.Minute)
	}

	return tm.cachedToken, nil
}
