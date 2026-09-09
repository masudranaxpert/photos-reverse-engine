package core

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

// WebClient interacts with Google Photos via Web RPCs using authentication cookies.
type WebClient struct {
	httpClient *http.Client
	cookie     Cookie
	globalData map[string]string
}

func generateWebID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// NewWebClient initializes a new Google Photos Web Client with the given cookies.
func NewWebClient(cookie Cookie) (*WebClient, error) {
	client := &WebClient{
		httpClient: &http.Client{
			Timeout: 60 * time.Second,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		cookie: cookie,
	}

	globalData, err := client.getGlobalData()
	if err != nil {
		return nil, fmt.Errorf("failed to fetch global session data: %w", err)
	}
	client.globalData = globalData

	return client, nil
}

func (c *WebClient) getGlobalData() (map[string]string, error) {
	cacheBust := fmt.Sprintf("https://photos.google.com/?_t=%d", time.Now().Unix())
	req, err := http.NewRequest("GET", cacheBust, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Cookie", c.cookie.BuildCookieHeader())
	req.Header.Set("User-Agent", webUserAgent)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("photos.google.com returned status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	bodyStr := string(body)

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

// SendBatchexecute posts an RPC request to Google Photos batchexecute endpoint and parses the response envelope.
func (c *WebClient) SendBatchexecute(rpcID string, payloadData interface{}, timeout time.Duration) (interface{}, error) {
	dataJSON, err := json.Marshal(payloadData)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal payload: %w", err)
	}

	batchedReq := [][]interface{}{
		{rpcID, string(dataJSON), nil, generateWebID()},
	}
	fReqJSON, err := json.Marshal([][][]interface{}{batchedReq})
	if err != nil {
		return nil, fmt.Errorf("failed to marshal f.req envelope: %w", err)
	}

	form := url.Values{}
	form.Set("f.req", string(fReqJSON))
	form.Set("at", c.globalData["at"])

	q := url.Values{}
	q.Set("rpcids", rpcID)
	q.Set("source-path", "/")
	q.Set("f.sid", c.globalData["f.sid"])
	q.Set("bl", c.globalData["bl"])
	q.Set("rt", "c")

	reqURL := "https://photos.google.com/_/PhotosUi/data/batchexecute?" + q.Encode()
	req, err := http.NewRequest("POST", reqURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
	req.Header.Set("Cookie", c.cookie.BuildCookieHeader())
	req.Header.Set("User-Agent", webUserAgent)

	client := c.httpClient
	if timeout > 0 {
		client = &http.Client{Timeout: timeout}
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("batchexecute request failed: %w", err)
	}
	defer resp.Body.Close()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	return parseBatchexecuteEnvelope(string(bodyBytes), rpcID)
}

func parseBatchexecuteEnvelope(body string, targetRPC string) (interface{}, error) {
	clean := strings.TrimSpace(body)
	if strings.HasPrefix(clean, ")]}'") {
		clean = strings.TrimSpace(clean[4:])
	}

	for _, line := range strings.Split(clean, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "[") {
			continue
		}

		var parsed []interface{}
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			continue
		}

		for _, chunk := range parsed {
			if chunkArr, ok := chunk.([]interface{}); ok && len(chunkArr) >= 3 {
				if rpc, ok := chunkArr[1].(string); ok && rpc == targetRPC {
					if payloadStr, ok := chunkArr[2].(string); ok {
						var innerData interface{}
						if err := json.Unmarshal([]byte(payloadStr), &innerData); err == nil {
							return innerData, nil
						}
						return payloadStr, nil
					}
					return chunkArr[2], nil
				}
			}
		}
	}

	return nil, fmt.Errorf("RPC %s not found in batchexecute response", targetRPC)
}

func safeGetIndex(data interface{}, indices ...int) interface{} {
	current := data
	for _, idx := range indices {
		arr, ok := current.([]interface{})
		if !ok || idx < 0 || idx >= len(arr) {
			return nil
		}
		current = arr[idx]
	}
	return current
}

// ImportFromDrive imports a Google Drive file into Google Photos via SusGud RPC and fetches download URL.
func (c *WebClient) ImportFromDrive(driveFileID string, mimeType string, cleanup bool) (*DriveImportResult, error) {
	if mimeType == "" {
		mimeType = "video/*"
	}

	// Payload matching SusGud: [[[driveFileID, mimeType]]]
	items := [][]interface{}{
		{driveFileID, mimeType},
	}
	payloadData := []interface{}{items}

	respData, err := c.SendBatchexecute("SusGud", payloadData, 120*time.Second)
	if err != nil {
		return nil, fmt.Errorf("import from drive request failed: %w", err)
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

// GetDownloadURL retrieves direct download URL and dedup key for a mediaKey using VrseUb RPC.
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

	return &DownloadInfo{
		MediaKey:    mediaKey,
		DedupKey:    dedupKey,
		DownloadURL: downloadURL,
	}, nil
}

// CreateShareLink creates a public photos.app.goo.gl link for a media key using SFKp8c RPC.
func (c *WebClient) CreateShareLink(mediaKey string) (*PublicShareLink, error) {
	fReq := fmt.Sprintf(
		`[[["SFKp8c","[null,null,[null,1,null,null,1,null,[[[1,1],0],[[1,2],0],[[2,1],1],[[2,2],1],[[3,1],1]]],[2,null,[[[\"%s\"]]],null,null,null,[1],0,null,null,null,null,null,0],null,null,null,null,[1,2,3,5,6]]",null,"generic"]]]`,
		mediaKey,
	)

	form := url.Values{}
	form.Set("f.req", fReq)
	form.Set("at", c.globalData["at"])

	q := url.Values{}
	q.Set("rpcids", "SFKp8c")
	q.Set("source-path", "/photo/"+mediaKey)
	q.Set("f.sid", c.globalData["f.sid"])
	q.Set("bl", c.globalData["bl"])
	q.Set("rt", "c")

	reqURL := "https://photos.google.com/_/PhotosUi/data/batchexecute?" + q.Encode()
	req, err := http.NewRequest("POST", reqURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
	req.Header.Set("Cookie", c.cookie.BuildCookieHeader())
	req.Header.Set("User-Agent", webUserAgent)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	shareRe := regexp.MustCompile(`"(https://photos\.app\.goo\.gl/([^"]+))"`)
	match := shareRe.FindStringSubmatch(string(bodyBytes))
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

// EmptyTrash empties Google Photos trash using vzCSKc RPC.
func (c *WebClient) EmptyTrash() error {
	payloadData := []interface{}{[]interface{}{}, nil, 1}
	_, err := c.SendBatchexecute("vzCSKc", payloadData, 30*time.Second)
	return err
}
