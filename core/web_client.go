package core

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/sardanioss/httpcloak"
)

// WebClient interacts with Google Photos via Web RPCs using authentic Firefox browser TLS emulation.
type WebClient struct {
	session    *httpcloak.Session
	globalData map[string]string
}

func generateWebID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// NewWebClient initializes a new Google Photos Web Client with cookies using httpcloak.
func NewWebClient(cookie Cookie) (*WebClient, error) {
	s := httpcloak.NewSession(
		"firefox-latest",
		httpcloak.WithoutRedirects(),
		httpcloak.WithSessionTimeout(60*time.Second),
	)
	cookie.LoadIntoSession(s)

	client := &WebClient{
		session: s,
	}

	globalData, err := client.getGlobalData()
	if err != nil {
		s.Close()
		return nil, fmt.Errorf("failed to fetch global session data: %w", err)
	}
	client.globalData = globalData

	return client, nil
}

// NewWebClientFromBlob restores an active WebClient from a serialized session_blob.
func NewWebClientFromBlob(blob []byte) (*WebClient, error) {
	s, err := httpcloak.UnmarshalSession(blob)
	if err != nil {
		return nil, fmt.Errorf("failed to unmarshal session blob: %w", err)
	}
	s.SetFollowRedirects(false)

	client := &WebClient{
		session: s,
	}

	globalData, err := client.getGlobalData()
	if err != nil {
		s.Close()
		return nil, fmt.Errorf("failed to fetch global session data: %w", err)
	}
	client.globalData = globalData

	return client, nil
}

// MarshalSession serializes the current live session (cookies, TLS state) to JSON bytes.
func (c *WebClient) MarshalSession() ([]byte, error) {
	if c.session == nil {
		return nil, errors.New("client session is closed")
	}
	return c.session.Marshal()
}

// Close releases session resources.
func (c *WebClient) Close() {
	if c.session != nil {
		c.session.Close()
	}
}

// GetCookies retrieves all current cookies from the live session jar.
func (c *WebClient) GetCookies() Cookie {
	return CookiesFromSession(c.session)
}

func (c *WebClient) getGlobalData() (map[string]string, error) {
	cacheBust := fmt.Sprintf("https://photos.google.com/?_t=%d", time.Now().Unix())
	resp, err := c.session.Get(context.Background(), cacheBust)
	if err != nil {
		return nil, err
	}
	defer resp.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("photos.google.com returned status %d", resp.StatusCode)
	}

	bodyStr, err := resp.Text()
	if err != nil {
		return nil, err
	}

	fsidRe := regexp.MustCompile(`"FdrFJe":"(.*?)"`)
	blRe := regexp.MustCompile(`"cfb2h":"(.*?)"`)
	atRe := regexp.MustCompile(`"SNlM0e":"(.*?)"`)

	fsidMatch := fsidRe.FindStringSubmatch(bodyStr)
	blMatch := blRe.FindStringSubmatch(bodyStr)
	atMatch := atRe.FindStringSubmatch(bodyStr)

	if len(fsidMatch) < 2 || len(blMatch) < 2 || len(atMatch) < 2 {
		return nil, errors.New("failed to parse global data tokens from photos.google.com (cookies may be invalid)")
	}

	return map[string]string{
		"f.sid": fsidMatch[1],
		"bl":    blMatch[1],
		"at":    atMatch[1],
	}, nil
}

// SendBatchexecute posts an RPC request to Google Photos batchexecute endpoint via httpcloak.
func (c *WebClient) SendBatchexecute(rpcID string, payloadData interface{}, timeout time.Duration) (interface{}, error) {
	dataJSON, err := json.Marshal(payloadData)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal payload: %w", err)
	}

	envJSON, err := json.Marshal([][][]interface{}{
		{
			{rpcID, string(dataJSON), nil, "generic"},
		},
	})
	if err != nil {
		return nil, fmt.Errorf("failed to build envelope: %w", err)
	}

	form := url.Values{}
	form.Set("f.req", string(envJSON))
	form.Set("at", c.globalData["at"])

	q := url.Values{}
	q.Set("rpcids", rpcID)
	q.Set("f.sid", c.globalData["f.sid"])
	q.Set("bl", c.globalData["bl"])
	q.Set("hl", "en-US")
	q.Set("soc-app", "1")
	q.Set("soc-platform", "1")
	q.Set("soc-device", "1")
	q.Set("_reqid", generateWebID())
	q.Set("rt", "c")

	reqURL := "https://photos.google.com/_/PhotosUi/data/batchexecute?" + q.Encode()

	ctx := context.Background()
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}

	req := &httpcloak.Request{
		Method: "POST",
		URL:    reqURL,
		Headers: map[string][]string{
			"Content-Type": {"application/x-www-form-urlencoded;charset=UTF-8"},
		},
		Body: strings.NewReader(form.Encode()),
	}

	resp, err := c.session.Do(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("batchexecute request failed: %w", err)
	}
	defer resp.Close()

	bodyStr, err := resp.Text()
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	return parseBatchexecuteEnvelope(bodyStr, rpcID)
}

func parseBatchexecuteEnvelope(body, rpcID string) (interface{}, error) {
	lines := strings.Split(body, "\n")
	var targetLine string
	for _, l := range lines {
		trimmed := strings.TrimSpace(l)
		if strings.HasPrefix(trimmed, `[["wrb.fr"`) || strings.HasPrefix(trimmed, `[`) {
			if strings.Contains(trimmed, rpcID) {
				targetLine = trimmed
				break
			}
			if targetLine == "" && (strings.HasPrefix(trimmed, `[[`) || strings.HasPrefix(trimmed, `[`)) {
				targetLine = trimmed
			}
		}
	}

	if targetLine == "" {
		return nil, fmt.Errorf("no valid batchexecute array envelope found in response")
	}

	var outer [][]interface{}
	if err := json.Unmarshal([]byte(targetLine), &outer); err != nil {
		var flat []interface{}
		if err2 := json.Unmarshal([]byte(targetLine), &flat); err2 == nil {
			for _, item := range flat {
				if itemArr, ok := item.([]interface{}); ok && len(itemArr) >= 3 {
					if id, ok := itemArr[1].(string); ok && id == rpcID {
						if payloadStr, ok := itemArr[2].(string); ok {
							var res interface{}
							if err3 := json.Unmarshal([]byte(payloadStr), &res); err3 == nil {
								return res, nil
							}
						}
					}
				}
			}
		}
		return nil, fmt.Errorf("failed to parse envelope array: %w", err)
	}

	for _, entry := range outer {
		if len(entry) >= 3 {
			id, _ := entry[1].(string)
			if id == rpcID {
				payloadStr, ok := entry[2].(string)
				if !ok || payloadStr == "" {
					return nil, nil
				}
				var res interface{}
				if err := json.Unmarshal([]byte(payloadStr), &res); err != nil {
					return nil, fmt.Errorf("failed to unmarshal inner payload string: %w", err)
				}
				return res, nil
			}
		}
	}

	for _, entry := range outer {
		if len(entry) >= 3 {
			if payloadStr, ok := entry[2].(string); ok && payloadStr != "" {
				var res interface{}
				if err := json.Unmarshal([]byte(payloadStr), &res); err == nil {
					return res, nil
				}
			}
		}
	}

	return nil, fmt.Errorf("rpcID %s not found in response envelope", rpcID)
}

func safeGetIndex(data interface{}, indices ...int) interface{} {
	curr := data
	for _, idx := range indices {
		arr, ok := curr.([]interface{})
		if !ok || idx < 0 || idx >= len(arr) {
			return nil
		}
		curr = arr[idx]
	}
	return curr
}

// ImportFromDrive imports a Google Drive file into Google Photos via SusGud RPC.
func (c *WebClient) ImportFromDrive(driveFileID, mimeType string, cleanup bool) (*DriveImportResult, error) {
	payloadData := []interface{}{
		[]interface{}{
			[]interface{}{
				driveFileID,
				[]interface{}{mimeType, nil, nil, nil, 1},
			},
		},
	}

	respData, err := c.SendBatchexecute("SusGud", payloadData, 45*time.Second)
	if err != nil {
		return nil, fmt.Errorf("SusGud RPC failed: %w", err)
	}

	mediaKey, _ := safeGetIndex(respData, 0, 0, 1, 0).(string)
	dedupKey, _ := safeGetIndex(respData, 0, 0, 1, 3).(string)

	if mediaKey == "" {
		mediaKey, _ = safeGetIndex(respData, 0, 1, 0).(string)
		dedupKey, _ = safeGetIndex(respData, 0, 1, 3).(string)
	}
	if mediaKey == "" {
		itemsArr := safeGetIndex(respData, 0)
		mediaKey, _ = safeGetIndex(itemsArr, 0, 1, 0).(string)
		dedupKey, _ = safeGetIndex(itemsArr, 0, 1, 3).(string)
	}

	if mediaKey == "" {
		return nil, fmt.Errorf("mediaKey not found in SusGud response: %v", respData)
	}

	result := &DriveImportResult{
		DriveFileID: driveFileID,
		MediaKey:    mediaKey,
		DedupKey:    dedupKey,
	}

	// Fetch direct download URL via VrseUb
	if dlInfo, err := c.GetDownloadURL(mediaKey); err == nil {
		result.DownloadURL = dlInfo.DownloadURL
		if result.DedupKey == "" {
			result.DedupKey = dlInfo.DedupKey
		}
	}

	// Cleanup if requested
	if cleanup && result.DedupKey != "" {
		_ = c.MoveToTrash([]string{result.DedupKey})
		_ = c.EmptyTrash()
	}

	return result, nil
}

// GetDownloadURL retrieves direct download URL and dedup key for a mediaKey using VrseUb RPC with photo page fallback.
func (c *WebClient) GetDownloadURL(mediaKey string) (*DownloadInfo, error) {
	payloadData := []interface{}{mediaKey, nil, nil, nil, nil}
	respData, err := c.SendBatchexecute("VrseUb", payloadData, 30*time.Second)
	if err != nil {
		return nil, fmt.Errorf("VrseUb request failed: %w", err)
	}

	dedupKey, _ := safeGetIndex(respData, 0, 3).(string)
	downloadURL, _ := safeGetIndex(respData, 1).(string)
	if downloadURL == "" {
		downloadURL, _ = safeGetIndex(respData, 7).(string)
	}
	if downloadURL == "" && dedupKey == "" {
		if arr, ok := respData.([]interface{}); ok && len(arr) > 0 {
			dedupKey, _ = safeGetIndex(arr, 0, 0, 3).(string)
			downloadURL, _ = safeGetIndex(arr, 0, 1).(string)
			if downloadURL == "" {
				downloadURL, _ = safeGetIndex(arr, 0, 7).(string)
			}
		}
	}

	// Fallback to direct HTML photo page fetch via httpcloak session
	if downloadURL == "" {
		photoURL := fmt.Sprintf("https://photos.google.com/photo/%s", mediaKey)
		resp, err := c.session.Get(context.Background(), photoURL)
		if err == nil {
			defer resp.Close()
			if resp.StatusCode == 200 {
				bodyStr, _ := resp.Text()
				videoURLPattern := regexp.MustCompile(`https://video-downloads\.googleusercontent\.com/[A-Za-z0-9_\-]+`)
				if m := videoURLPattern.FindString(bodyStr); m != "" {
					downloadURL = m
				}
			}
		}
	}

	return &DownloadInfo{
		MediaKey:    mediaKey,
		DownloadURL: downloadURL,
		DedupKey:    dedupKey,
	}, nil
}

// CreateShareLink creates public photos.app.goo.gl link via Go core SFKp8c RPC.
func (c *WebClient) CreateShareLink(mediaKey string) (*PublicShareLink, error) {
	payload := fmt.Sprintf(`[null,null,null,null,null,null,null,null,["%s"]]`, mediaKey)
	envelope := fmt.Sprintf(`[[["SFKp8c","%s",null,"generic"]]]`, strings.ReplaceAll(payload, `"`, `\"`))

	form := url.Values{}
	form.Set("f.req", envelope)
	form.Set("at", c.globalData["at"])

	q := url.Values{}
	q.Set("rpcids", "SFKp8c")
	q.Set("source-path", fmt.Sprintf("/photo/%s", mediaKey))
	q.Set("f.sid", c.globalData["f.sid"])
	q.Set("bl", c.globalData["bl"])
	q.Set("hl", "en-US")
	q.Set("_reqid", generateWebID())
	q.Set("rt", "c")

	reqURL := "https://photos.google.com/_/PhotosUi/data/batchexecute?" + q.Encode()

	req := &httpcloak.Request{
		Method: "POST",
		URL:    reqURL,
		Headers: map[string][]string{
			"Content-Type": {"application/x-www-form-urlencoded;charset=UTF-8"},
		},
		Body: strings.NewReader(form.Encode()),
	}

	resp, err := c.session.Do(context.Background(), req)
	if err != nil {
		return nil, err
	}
	defer resp.Close()

	bodyStr, err := resp.Text()
	if err != nil {
		return nil, err
	}

	shareRe := regexp.MustCompile(`"(https://photos\.app\.goo\.gl/([^"]+))"`)
	match := shareRe.FindStringSubmatch(bodyStr)
	if len(match) < 3 {
		return nil, errors.New("could not find share link in response")
	}

	shareURL := strings.ReplaceAll(match[1], `\`, "")
	shortID := strings.ReplaceAll(match[2], `\`, "")

	return &PublicShareLink{
		ShareURL:    shareURL,
		EnvelopeKey: shortID,
		MediaKeys:   []string{mediaKey},
	}, nil
}

// MoveToTrash moves dedup keys to trash using XwAOJf RPC.
func (c *WebClient) MoveToTrash(dedupKeys []string) error {
	payloadData := []interface{}{nil, 1, dedupKeys, 3}
	_, err := c.SendBatchexecute("XwAOJf", payloadData, 30*time.Second)
	return err
}

// EmptyTrash empties the trash using e2FP6c RPC.
func (c *WebClient) EmptyTrash() error {
	payloadData := []interface{}{nil, 2}
	_, err := c.SendBatchexecute("e2FP6c", payloadData, 30*time.Second)
	return err
}
