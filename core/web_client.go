package core

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/url"
	"regexp"
	"strconv"
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

// parseRPCError inspects error structure in batchexecute array index 5
func parseRPCError(errVal interface{}) error {
	if errVal == nil {
		return nil
	}
	b, err := json.Marshal(errVal)
	if err != nil {
		return fmt.Errorf("RPC error: %v", errVal)
	}
	s := string(b)
	if strings.Contains(s, "PhotosWebImportDriveItemsFailure") || strings.Contains(s, "[8,") || strings.Contains(s, "[8]") {
		return errors.New("STORAGE_QUOTA_EXCEEDED: Google Photos storage is full (PhotosWebImportDriveItemsFailure)")
	}
	if strings.Contains(s, "[13]") || strings.Contains(s, "[13,") {
		return errors.New("RPC_TIMEOUT: Google Photos RPC deadline/internal timeout exceeded (code 13)")
	}
	return fmt.Errorf("RPC_ERROR: %s", s)
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
				if itemArr, ok := item.([]interface{}); ok && len(itemArr) >= 2 {
					if id, ok := itemArr[1].(string); ok && id == rpcID {
						var rpcErr error
						if len(itemArr) >= 6 && itemArr[5] != nil {
							rpcErr = parseRPCError(itemArr[5])
						}
						if len(itemArr) >= 3 {
							payloadStr, ok := itemArr[2].(string)
							if !ok || payloadStr == "" || payloadStr == "null" {
								if rpcErr != nil {
									return nil, rpcErr
								}
								return nil, nil
							}
							var res interface{}
							if err3 := json.Unmarshal([]byte(payloadStr), &res); err3 == nil {
								if rpcErr != nil {
									return res, rpcErr
								}
								return res, nil
							}
						}
						if rpcErr != nil {
							return nil, rpcErr
						}
					}
				}
			}
		}
		return nil, fmt.Errorf("failed to parse envelope array: %w", err)
	}

	for _, entry := range outer {
		if len(entry) >= 2 {
			id, _ := entry[1].(string)
			if id == rpcID {
				var rpcErr error
				if len(entry) >= 6 && entry[5] != nil {
					rpcErr = parseRPCError(entry[5])
				}
				if len(entry) >= 3 {
					payloadStr, ok := entry[2].(string)
					if !ok || payloadStr == "" || payloadStr == "null" {
						if rpcErr != nil {
							return nil, rpcErr
						}
						return nil, nil
					}
					var res interface{}
					if err := json.Unmarshal([]byte(payloadStr), &res); err != nil {
						if rpcErr != nil {
							return nil, rpcErr
						}
						return nil, fmt.Errorf("failed to unmarshal inner payload string: %w", err)
					}
					if rpcErr != nil {
						return res, rpcErr
					}
					return res, nil
				}
				if rpcErr != nil {
					return nil, rpcErr
				}
			}
		}
	}

	for _, entry := range outer {
		if len(entry) >= 3 {
			if payloadStr, ok := entry[2].(string); ok && payloadStr != "" && payloadStr != "null" {
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

// BatchImportFromDrive imports multiple Google Drive files into Google Photos in a single SusGud RPC request.
func (c *WebClient) BatchImportFromDrive(items []DriveBatchItem, cleanup bool, timeout time.Duration) (*DriveBatchImportResult, error) {
	if len(items) == 0 {
		return nil, errors.New("no drive items provided for import")
	}

	if timeout <= 0 {
		timeout = 120 * time.Second
	}

	// Payload format: [[ [ [id1, mime1], [id2, mime2], ... ] ]]
	drivePairs := make([][]interface{}, 0, len(items))
	for _, it := range items {
		mime := it.MimeType
		if mime == "" {
			mime = "video/*"
		}
		drivePairs = append(drivePairs, []interface{}{it.DriveFileID, mime})
	}
	payloadData := []interface{}{
		drivePairs,
	}

	result := &DriveBatchImportResult{
		Items: make([]DriveImportItemResult, 0, len(items)),
	}

	respData, err := c.SendBatchexecute("SusGud", payloadData, timeout)
	if err != nil {
		errStr := err.Error()
		if strings.Contains(errStr, "STORAGE_QUOTA_EXCEEDED") {
			result.QuotaExceeded = true
			result.ErrorMessage = "Google Photos storage quota is full. Import failed."
			result.FailedCount = len(items)
			for _, it := range items {
				result.Items = append(result.Items, DriveImportItemResult{
					DriveFileID: it.DriveFileID,
					Status:      8,
					Error:       "Storage quota exceeded",
				})
			}
			return result, err
		}
		return nil, fmt.Errorf("SusGud batch import failed: %w", err)
	}

	// Capture raw response for debugging and inspectability
	if rawBytes, err := json.Marshal(respData); err == nil {
		result.RawResponse = string(rawBytes)
	}

	// Parse items from response
	itemsArr := safeGetIndex(respData, 0)
	list, ok := itemsArr.([]interface{})
	if !ok {
		list, _ = respData.([]interface{})
	}

	var dedupKeysToCleanup []string

	for _, rawItem := range list {
		sub, ok := rawItem.([]interface{})
		if !ok || len(sub) == 0 {
			continue
		}

		driveID, _ := sub[0].(string)
		itemRes := DriveImportItemResult{
			DriveFileID: driveID,
		}
		if rawSub, err := json.Marshal(sub); err == nil {
			itemRes.RawItem = string(rawSub)
		}

		if len(sub) > 2 {
			if st, ok := sub[2].(float64); ok {
				itemRes.Status = int(st)
			}
		}

		meta := safeGetIndex(sub, 1)
		if metaArr, ok := meta.([]interface{}); ok && len(metaArr) > 0 {
			itemRes.MediaKey, _ = safeGetIndex(metaArr, 0).(string)
			itemRes.DedupKey, _ = safeGetIndex(metaArr, 3).(string)

			// URL and dimensions
			itemRes.DownloadURL, _ = safeGetIndex(metaArr, 1, 0).(string)
			if w, ok := safeGetIndex(metaArr, 1, 1).(float64); ok {
				itemRes.Width = int(w)
			}
			if h, ok := safeGetIndex(metaArr, 1, 2).(float64); ok {
				itemRes.Height = int(h)
			}

			// File size from metadata dictionary
			if metaDict, ok := safeGetIndex(metaArr, 9).(map[string]interface{}); ok {
				if sizeArr, ok := metaDict["76647426"].([]interface{}); ok && len(sizeArr) > 0 {
					if sz, ok := sizeArr[0].(float64); ok {
						itemRes.FileSize = int64(sz)
					}
				}
			}
		}

		if itemRes.MediaKey != "" && itemRes.Status == 0 {
			result.SuccessCount++
			if itemRes.DedupKey != "" {
				dedupKeysToCleanup = append(dedupKeysToCleanup, itemRes.DedupKey)
			}
		} else {
			result.FailedCount++
			if itemRes.Error == "" {
				switch itemRes.Status {
				case 1:
					itemRes.Error = "Processing (status 1)"
				case 3:
					itemRes.Error = "Unsupported format or rejected by Google Photos (status 3)"
				default:
					itemRes.Error = fmt.Sprintf("Import status %d", itemRes.Status)
				}
			}
		}

		result.Items = append(result.Items, itemRes)
	}

	if cleanup && len(dedupKeysToCleanup) > 0 {
		_ = c.MoveToTrash(dedupKeysToCleanup)
		_ = c.EmptyTrash()
	}

	return result, nil
}

// ImportFromDriveWithContext imports a single Google Drive file using the provided context for timeout control.
func (c *WebClient) ImportFromDriveWithContext(ctx context.Context, driveFileID, mimeType string, cleanup bool) (*DriveImportResult, error) {
	timeout := 120 * time.Second // fallback; ctx deadline takes priority
	if deadline, ok := ctx.Deadline(); ok {
		remaining := time.Until(deadline)
		if remaining > 0 {
			timeout = remaining
		}
	}
	return importFromDriveInternal(c, driveFileID, mimeType, cleanup, timeout)
}

// ImportFromDrive imports a single Google Drive file into Google Photos via SusGud RPC.
func (c *WebClient) ImportFromDrive(driveFileID, mimeType string, cleanup bool) (*DriveImportResult, error) {
	return importFromDriveInternal(c, driveFileID, mimeType, cleanup, 120*time.Second)
}

func importFromDriveInternal(c *WebClient, driveFileID, mimeType string, cleanup bool, timeout time.Duration) (*DriveImportResult, error) {
	batchRes, err := c.BatchImportFromDrive([]DriveBatchItem{
		{DriveFileID: driveFileID, MimeType: mimeType},
	}, cleanup, timeout)
	if err != nil {
		return nil, err
	}
	if len(batchRes.Items) == 0 || batchRes.Items[0].MediaKey == "" {
		if len(batchRes.Items) > 0 {
			it := batchRes.Items[0]
			if it.Status == 3 {
				return nil, fmt.Errorf("file rejected by Google Photos (status 3: unsupported format or non-media file): %s", driveFileID)
			}
			return nil, fmt.Errorf("import failed (status %d): %s", it.Status, it.Error)
		}
		return nil, fmt.Errorf("mediaKey not found in SusGud response")
	}

	item := batchRes.Items[0]
	res := &DriveImportResult{
		DriveFileID: item.DriveFileID,
		MediaKey:    item.MediaKey,
		DedupKey:    item.DedupKey,
		DownloadURL: item.DownloadURL,
	}

	// If download URL wasn't returned in metadata, fetch via VrseUb
	if res.DownloadURL == "" {
		if dlInfo, err := c.GetDownloadURL(res.MediaKey); err == nil {
			res.DownloadURL = dlInfo.DownloadURL
			if res.DedupKey == "" {
				res.DedupKey = dlInfo.DedupKey
			}
		}
	}

	return res, nil
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
	payload := fmt.Sprintf(`[null,null,[null,1,null,null,1,null,[[[1,1],0],[[1,2],0],[[2,1],1],[[2,2],1],[[3,1],1]]],[2,null,[[["%s"]]],null,null,null,[1],0,null,null,null,null,null,0],null,null,null,null,[1,2,3,5,6]]`, mediaKey)
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

// ListLibraryItems enumerates library items via lcxiM RPC.
// Returns dedupKeys, next_page_id, last_timestamp, error.
func (c *WebClient) ListLibraryItems(pageSize int, pageID string, lastTimestamp int64) ([]string, string, int64, error) {
	if pageSize <= 0 {
		pageSize = 500
	}
	var tsVal interface{} = nil
	if lastTimestamp > 0 {
		tsVal = lastTimestamp
	}
	var pageVal interface{} = nil
	if pageID != "" {
		pageVal = pageID
	}

	// lcxiM: [page_id, timestamp, page_size, nil, 1, 3] (3 = both library and archive)
	payloadData := []interface{}{pageVal, tsVal, pageSize, nil, 1, 3}
	respData, err := c.SendBatchexecute("lcxiM", payloadData, 45*time.Second)
	if err != nil {
		return nil, "", 0, fmt.Errorf("lcxiM RPC failed: %w", err)
	}

	itemsArr := safeGetIndex(respData, 0)
	list, ok := itemsArr.([]interface{})
	if !ok {
		return nil, "", 0, nil
	}

	var dedupKeys []string
	for _, rawItem := range list {
		item, ok := rawItem.([]interface{})
		if !ok || len(item) < 4 {
			continue
		}
		if dedup, ok := item[3].(string); ok && dedup != "" {
			dedupKeys = append(dedupKeys, dedup)
		}
	}

	var nextPID string
	if np, ok := safeGetIndex(respData, 1).(string); ok {
		nextPID = np
	}

	var nextTS int64
	if ts, ok := safeGetIndex(respData, 2).(float64); ok {
		nextTS = int64(ts)
	} else if tsStr, ok := safeGetIndex(respData, 2).(string); ok {
		nextTS, _ = strconv.ParseInt(tsStr, 10, 64)
	}

	return dedupKeys, nextPID, nextTS, nil
}

// ResetAccount clears the Google Photos library: moves all items to trash via XwAOJf, then empties trash via e2FP6c.
func (c *WebClient) ResetAccount(timeout time.Duration) (*AccountResetResult, error) {
	totalDeleted := 0
	pageID := ""
	var lastTS int64 = 0

	for {
		keys, nextPID, nextTS, err := c.ListLibraryItems(500, pageID, lastTS)
		if err != nil {
			return nil, fmt.Errorf("failed listing library items: %w", err)
		}

		if len(keys) > 0 {
			if err := c.MoveToTrash(keys); err != nil {
				return nil, fmt.Errorf("failed moving items to trash: %w", err)
			}
			totalDeleted += len(keys)
		}

		if nextPID == "" || nextPID == pageID {
			break
		}
		pageID = nextPID
		lastTS = nextTS
	}

	// Permanently empty trash
	if err := c.EmptyTrash(); err != nil {
		return &AccountResetResult{
			Success:      true,
			TotalDeleted: totalDeleted,
			TrashEmptied: false,
			Message:      fmt.Sprintf("Moved %d items to trash, but emptying trash returned: %v", totalDeleted, err),
		}, nil
	}

	return &AccountResetResult{
		Success:      true,
		TotalDeleted: totalDeleted,
		TrashEmptied: true,
		Message:      fmt.Sprintf("Successfully removed %d items from library and permanently emptied trash.", totalDeleted),
	}, nil
}

// GetStorageQuota fetches storage quota information from Google Photos quota management.
func (c *WebClient) GetStorageQuota() (*StorageQuota, error) {
	// First check /quotamanagement endpoint
	quotaURL := "https://photos.google.com/quotamanagement"
	resp, err := c.session.Get(context.Background(), quotaURL)
	if err == nil {
		defer resp.Close()
		if resp.StatusCode == 200 {
			bodyStr, _ := resp.Text()
			if quota, qErr := parseStorageQuotaHTML(bodyStr); qErr == nil {
				return quota, nil
			}
		}
	}

	// Fallback to main page https://photos.google.com/ which also contains quota link and bars in sidebar
	mainURL := fmt.Sprintf("https://photos.google.com/?_t=%d", time.Now().Unix())
	respMain, err := c.session.Get(context.Background(), mainURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch Google Photos storage quota: %w", err)
	}
	defer respMain.Close()

	if respMain.StatusCode != 200 {
		return nil, fmt.Errorf("photos.google.com returned status %d", respMain.StatusCode)
	}

	bodyStr, err := respMain.Text()
	if err != nil {
		return nil, err
	}

	return parseStorageQuotaHTML(bodyStr)
}

// parseStorageQuotaHTML extracts storage quota and percentage bars from Google Photos HTML.
func parseStorageQuotaHTML(htmlStr string) (*StorageQuota, error) {
	quota := &StorageQuota{}

	// 1. Extract usage text from <a href="./quotamanagement" ...>9.3 GB of 15 GB used</a>
	aRe := regexp.MustCompile(`href=["'](?:\./)?quotamanagement[^"']*["'][^>]*>([^<]+)</a>`)
	if m := aRe.FindStringSubmatch(htmlStr); len(m) > 1 {
		quota.UsageText = strings.TrimSpace(m[1])
	}

	if quota.UsageText == "" {
		fallbackRe := regexp.MustCompile(`([0-9.,]+\s*(?:KB|MB|GB|TB))\s+of\s+([0-9.,]+\s*(?:KB|MB|GB|TB))\s+used`)
		if m := fallbackRe.FindStringSubmatch(htmlStr); len(m) > 0 {
			quota.UsageText = strings.TrimSpace(m[0])
		}
	}

	// 2. Parse used and total display strings (e.g. "9.3 GB" and "15 GB")
	textPartsRe := regexp.MustCompile(`([0-9.,]+\s*(?:KB|MB|GB|TB))\s+of\s+([0-9.,]+\s*(?:KB|MB|GB|TB))`)
	if m := textPartsRe.FindStringSubmatch(quota.UsageText); len(m) > 2 {
		quota.UsedDisplay = strings.TrimSpace(m[1])
		quota.TotalDisplay = strings.TrimSpace(m[2])
		quota.UsedBytes = parseSizeToBytes(quota.UsedDisplay)
		quota.TotalBytes = parseSizeToBytes(quota.TotalDisplay)
	}

	// 3. Extract used progress percentage from class="XCxRFf" style="width:61.7%;"
	usedBarRe := regexp.MustCompile(`class=["'][^"']*XCxRFf[^"']*["'][^>]*style=["'][^"']*width:\s*([0-9.]+)%`)
	if m := usedBarRe.FindStringSubmatch(htmlStr); len(m) > 1 {
		if val, err := strconv.ParseFloat(m[1], 64); err == nil {
			quota.UsedPercent = val
		}
	}

	// 4. Extract free progress percentage from class="DFG23b" style="width:38.3%;"
	freeBarRe := regexp.MustCompile(`class=["'][^"']*DFG23b[^"']*["'][^>]*style=["'][^"']*width:\s*([0-9.]+)%`)
	if m := freeBarRe.FindStringSubmatch(htmlStr); len(m) > 1 {
		if val, err := strconv.ParseFloat(m[1], 64); err == nil {
			quota.FreePercent = val
		}
	}

	// Calculate missing percentages if one is known
	if quota.UsedPercent > 0 && quota.FreePercent == 0 {
		quota.FreePercent = math.Round((100.0-quota.UsedPercent)*10) / 10
	} else if quota.FreePercent > 0 && quota.UsedPercent == 0 {
		quota.UsedPercent = math.Round((100.0-quota.FreePercent)*10) / 10
	} else if quota.UsedPercent == 0 && quota.TotalBytes > 0 {
		quota.UsedPercent = math.Round((float64(quota.UsedBytes)/float64(quota.TotalBytes))*1000) / 10
		quota.FreePercent = math.Round((100.0-quota.UsedPercent)*10) / 10
	}

	if quota.UsageText == "" && quota.UsedPercent == 0 && quota.TotalBytes == 0 {
		return nil, errors.New("storage quota elements not found in Google Photos response")
	}

	return quota, nil
}

// parseSizeToBytes converts strings like "9.3 GB" or "15 GB" to byte count.
func parseSizeToBytes(sizeStr string) int64 {
	sizeStr = strings.TrimSpace(strings.ToUpper(sizeStr))
	re := regexp.MustCompile(`^([0-9.,]+)\s*([A-Z]+)$`)
	match := re.FindStringSubmatch(sizeStr)
	if len(match) < 3 {
		return 0
	}
	numStr := strings.ReplaceAll(match[1], ",", "")
	num, err := strconv.ParseFloat(numStr, 64)
	if err != nil {
		return 0
	}

	var multiplier float64 = 1
	switch match[2] {
	case "B":
		multiplier = 1
	case "KB":
		multiplier = 1024
	case "MB":
		multiplier = 1024 * 1024
	case "GB":
		multiplier = 1024 * 1024 * 1024
	case "TB":
		multiplier = 1024 * 1024 * 1024 * 1024
	}

	return int64(num * multiplier)
}
