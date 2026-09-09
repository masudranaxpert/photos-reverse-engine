package core

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

// Cookie contains authentication credentials for Google Photos Web Client.
type Cookie struct {
	SID           string `json:"sid"`
	Secure1PSID   string `json:"secure_1psid"`
	Secure1PSIDTS string `json:"secure_1psidts"`
	OSID          string `json:"osid"`
}

// BuildCookieHeader formats Cookie into a standard Cookie request header.
func (c Cookie) BuildCookieHeader() string {
	var parts []string
	if c.SID != "" {
		parts = append(parts, "SID="+c.SID)
	}
	if c.Secure1PSID != "" {
		parts = append(parts, "__Secure-1PSID="+c.Secure1PSID)
	}
	if c.Secure1PSIDTS != "" {
		parts = append(parts, "__Secure-1PSIDTS="+c.Secure1PSIDTS)
	}
	if c.OSID != "" {
		parts = append(parts, "OSID="+c.OSID)
	}
	return strings.Join(parts, "; ")
}

// ParseCookies parses raw cookie string (Netscape format, JSON, or key=value header).
func ParseCookies(raw string) (Cookie, error) {
	clean := strings.TrimSpace(raw)
	clean = strings.Trim(clean, "'\"")
	if clean == "" {
		return Cookie{}, errors.New("empty cookie string")
	}

	cookie := Cookie{}

	// 1. Try JSON format
	if strings.HasPrefix(clean, "[") || strings.HasPrefix(clean, "{") {
		var list []map[string]interface{}
		if err := json.Unmarshal([]byte(clean), &list); err == nil {
			for _, item := range list {
				name, _ := item["name"].(string)
				val, _ := item["value"].(string)
				applyCookieField(&cookie, name, val)
			}
			if cookie.SID != "" || cookie.Secure1PSID != "" {
				return cookie, nil
			}
		}

		var obj map[string]interface{}
		if err := json.Unmarshal([]byte(clean), &obj); err == nil {
			if cookiesArr, ok := obj["cookies"].([]interface{}); ok {
				for _, cItem := range cookiesArr {
					if cMap, ok := cItem.(map[string]interface{}); ok {
						name, _ := cMap["name"].(string)
						val, _ := cMap["value"].(string)
						applyCookieField(&cookie, name, val)
					}
				}
			} else {
				for k, v := range obj {
					if strVal, ok := v.(string); ok {
						applyCookieField(&cookie, k, strVal)
					}
				}
			}
			if cookie.SID != "" || cookie.Secure1PSID != "" {
				return cookie, nil
			}
		}
	}

	// 2. Try Netscape or line-by-line format
	lines := strings.Split(clean, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" || (strings.HasPrefix(line, "#") && !strings.HasPrefix(line, "#HttpOnly_")) {
			continue
		}
		if strings.HasPrefix(line, "#HttpOnly_") {
			line = strings.TrimPrefix(line, "#HttpOnly_")
		}

		parts := strings.Split(line, "\t")
		if len(parts) >= 7 {
			name := strings.TrimSpace(parts[5])
			val := strings.TrimSpace(parts[6])
			applyCookieField(&cookie, name, val)
			continue
		}

		// Try semi-colon or whitespace delimited key=value
		subParts := strings.Split(line, ";")
		for _, sp := range subParts {
			sp = strings.TrimSpace(sp)
			if eqIdx := strings.Index(sp, "="); eqIdx != -1 {
				name := strings.TrimSpace(sp[:eqIdx])
				val := strings.TrimSpace(sp[eqIdx+1:])
				applyCookieField(&cookie, name, val)
			}
		}
	}

	if cookie.SID == "" && cookie.Secure1PSID == "" {
		return Cookie{}, errors.New("no valid Google auth cookies found (SID or __Secure-1PSID required)")
	}

	return cookie, nil
}

func applyCookieField(c *Cookie, name, val string) {
	name = strings.TrimSpace(name)
	val = strings.TrimSpace(val)
	switch name {
	case "SID":
		c.SID = val
	case "__Secure-1PSID":
		c.Secure1PSID = val
	case "__Secure-1PSIDTS":
		c.Secure1PSIDTS = val
	case "OSID":
		c.OSID = val
	}
}

const webUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

// CheckCookieStatus verifies cookie validity and retrieves the logged-in email.
func CheckCookieStatus(cookie Cookie) (*CookieStatus, error) {
	client := &http.Client{
		Timeout: 15 * time.Second,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	checkURL := fmt.Sprintf("https://photos.google.com/?_t=%d", time.Now().Unix())
	req, err := http.NewRequest("GET", checkURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Cookie", cookie.BuildCookieHeader())
	req.Header.Set("User-Agent", webUserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("network error: %w", err)
	}
	defer resp.Body.Close()

	location := resp.Header.Get("Location")
	if resp.StatusCode != 200 || strings.Contains(location, "accounts.google.com") || strings.Contains(location, "photos/about") {
		return &CookieStatus{
			Valid:   false,
			Message: "Cookies are expired or redirected to login.",
		}, nil
	}

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}
	bodyStr := string(bodyBytes)

	// Pattern 1: oPEP7c
	accountRe := regexp.MustCompile(`"oPEP7c"\s*:\s*"([^"]+@[^"]+)"`)
	if match := accountRe.FindStringSubmatch(bodyStr); len(match) > 1 {
		account := strings.TrimSpace(match[1])
		return &CookieStatus{
			Valid:   true,
			Account: account,
			Message: fmt.Sprintf("Cookies are valid (Account: %s)", account),
		}, nil
	}

	// Pattern 2: Generic email structure
	emailRe := regexp.MustCompile(`([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})`)
	if match := emailRe.FindStringSubmatch(bodyStr); len(match) > 1 {
		account := strings.TrimSpace(match[1])
		return &CookieStatus{
			Valid:   true,
			Account: account,
			Message: fmt.Sprintf("Cookies are valid (Account: %s)", account),
		}, nil
	}

	return &CookieStatus{
		Valid:   true,
		Message: "Cookies are valid (Account email could not be parsed).",
	}, nil
}
