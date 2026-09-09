package gpmc

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	defaultUserAgent = "com.google.android.apps.photos/49029607 (Linux; U; Android 9; en_US; Pixel XL; Build/PQ2A.190205.001; Cronet/127.0.6510.5) (gzip)"
	defaultLanguage  = "en-US"

	endpointPrepareDownload = "https://photosdata-pa.googleapis.com/$rpc/social.frontend.photos.preparedownloaddata.v1.PhotosPrepareDownloadDataService/PhotosPrepareDownload"
	endpointSaveImport      = "https://photosdata-pa.googleapis.com/6439526531001121323/2949048824736983350"
	endpointCreateAlbum     = "https://photosdata-pa.googleapis.com/6439526531001121323/8386163679468898444"
	endpointDeletePermanent = "https://photosdata-pa.googleapis.com/6439526531001121323/17490284929287180316"
	endpointFindByHash      = "https://photosdata-pa.googleapis.com/6439526531001121323/5084965799730810217"
	endpointCreateShareLink = "https://photosdata-pa.googleapis.com/6439526531001121323/11663664809460121647"
)

// Client represents the high-level Google Photos client.
type Client struct {
	tokenManager *TokenManager
	httpClient   *http.Client
	userAgent    string
	language     string
}

// NewClient initializes a new Google Photos Client with the provided AUTH_DATA.
func NewClient(authData string) (*Client, error) {
	tm, err := NewTokenManager(authData)
	if err != nil {
		return nil, err
	}

	return &Client{
		tokenManager: tm,
		httpClient: &http.Client{
			Timeout: 45 * time.Second,
		},
		userAgent: defaultUserAgent,
		language:  defaultLanguage,
	}, nil
}

// GetToken returns a valid OAuth2 Bearer token, refreshing if necessary.
func (c *Client) GetToken(ctx context.Context) (string, error) {
	return c.tokenManager.GetToken(ctx)
}

func readBody(resp *http.Response) ([]byte, error) {
	var reader io.Reader = resp.Body
	if strings.EqualFold(resp.Header.Get("Content-Encoding"), "gzip") {
		gz, err := gzip.NewReader(resp.Body)
		if err != nil {
			return nil, fmt.Errorf("failed to create gzip reader: %w", err)
		}
		defer gz.Close()
		reader = gz
	}
	return io.ReadAll(reader)
}

func (c *Client) sendRequest(ctx context.Context, url string, body []byte) ([]byte, error) {
	token, err := c.tokenManager.GetToken(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get access token: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create HTTP request: %w", err)
	}

	req.Header.Set("Accept-Encoding", "gzip")
	req.Header.Set("Accept-Language", c.language)
	req.Header.Set("Content-Type", "application/x-protobuf")
	req.Header.Set("User-Agent", c.userAgent)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Connection", "Keep-Alive")
	req.Header.Set("x-goog-ext-173412678-bin", "CgcIAhClARgC")
	req.Header.Set("x-goog-ext-174067345-bin", "CgIIAg==")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	respBytes, err := readBody(resp)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// Retry once on 401 Unauthorized by invalidating token
	if resp.StatusCode == http.StatusUnauthorized {
		c.tokenManager.Invalidate()
		token, err = c.tokenManager.GetToken(ctx)
		if err == nil {
			req.Header.Set("Authorization", "Bearer "+token)
			if retryResp, err := c.httpClient.Do(req); err == nil {
				defer retryResp.Body.Close()
				if retryResp.StatusCode == http.StatusOK {
					return readBody(retryResp)
				}
			}
		}
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API returned error status %d: %s", resp.StatusCode, string(respBytes))
	}

	return respBytes, nil
}

// GetDownloadURL retrieves the direct download URL, filename, size, and SHA-1 for a media_key.
func (c *Client) GetDownloadURL(ctx context.Context, mediaKey string) (*DownloadInfo, error) {
	payload := BuildDownloadPayload(mediaKey)
	respBytes, err := c.sendRequest(ctx, endpointPrepareDownload, payload)
	if err != nil {
		return nil, fmt.Errorf("GetDownloadURL failed: %w", err)
	}

	nodes, err := ParseProtobuf(respBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to decode download response: %w", err)
	}

	info := &DownloadInfo{
		MediaKey: mediaKey,
	}

	for _, root := range nodes {
		if root.FieldNum == 1 {
			// Extract filename and size from field 1.2
			if f2 := root.FindFirstChild(2); f2 != nil {
				if f4 := f2.FindFirstChild(4); f4 != nil {
					info.Filename = f4.StringValue
				}
				if f10 := f2.FindFirstChild(10); f10 != nil {
					info.FileSize = int64(f10.VarintValue)
				}
				if f13 := f2.FindFirstChild(13); f13 != nil {
					if f1 := f13.FindFirstChild(1); f1 != nil && len(f1.BytesValue) > 0 {
						info.Sha1Bytes = f1.BytesValue
						info.Sha1Hex = hex.EncodeToString(f1.BytesValue)
						info.DedupKey = urlSafeBase64(f1.BytesValue)
					}
				}
			}

			// Extract download link from field 1.5
			if f5 := root.FindFirstChild(5); f5 != nil {
				// Video stream link
				if f3 := f5.FindFirstChild(3); f3 != nil {
					if streamLink := f3.FindFirstChild(5); streamLink != nil && streamLink.StringValue != "" {
						info.DownloadURL = streamLink.StringValue
					}
				}
				// Fallback to image stream link
				if info.DownloadURL == "" {
					if f2 := f5.FindFirstChild(2); f2 != nil {
						if imgLink := f2.FindFirstChild(1); imgLink != nil {
							info.DownloadURL = imgLink.StringValue
						}
					}
				}
			}
		}
	}

	if info.DownloadURL == "" && info.Filename == "" {
		return nil, fmt.Errorf("media not found or download link unavailable for %s", mediaKey)
	}

	return info, nil
}

// CreateAlbum creates a shared album containing the specified media keys.
func (c *Client) CreateAlbum(ctx context.Context, albumName string, mediaKeys []string) (*ShareInfo, error) {
	if len(mediaKeys) == 0 {
		return nil, fmt.Errorf("at least one media_key is required")
	}

	payload := BuildCreateAlbumPayload(albumName, time.Now().Unix(), mediaKeys)
	respBytes, err := c.sendRequest(ctx, endpointCreateAlbum, payload)
	if err != nil {
		return nil, fmt.Errorf("CreateAlbum failed: %w", err)
	}

	nodes, err := ParseProtobuf(respBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to decode CreateAlbum response: %w", err)
	}

	albumKey := ""
	for _, root := range nodes {
		if root.FieldNum == 1 {
			if f1 := root.FindFirstChild(1); f1 != nil {
				albumKey = f1.StringValue
				break
			}
		}
	}

	if albumKey == "" {
		return nil, fmt.Errorf("album creation succeeded but album_media_key was missing")
	}

	return &ShareInfo{
		AlbumName:     albumName,
		AlbumMediaKey: albumKey,
		MediaKeys:     mediaKeys,
	}, nil
}

// CreateShareLink generates a public photos.app.goo.gl link for single or multiple media keys.
func (c *Client) CreateShareLink(ctx context.Context, mediaKeys []string) (*PublicShareLink, error) {
	if len(mediaKeys) == 0 {
		return nil, fmt.Errorf("mediaKeys cannot be empty")
	}

	payload := BuildCreateShareLinkPayload(mediaKeys, time.Now().UnixMilli())
	respBytes, err := c.sendRequest(ctx, endpointCreateShareLink, payload)
	if err != nil {
		return nil, fmt.Errorf("CreateShareLink failed: %w", err)
	}

	nodes, err := ParseProtobuf(respBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to parse share link response: %w", err)
	}

	link := &PublicShareLink{
		MediaKeys: mediaKeys,
	}

	for _, root := range nodes {
		switch root.FieldNum {
		case 1:
			link.EnvelopeKey = root.StringValue
		case 2:
			link.ShareURL = root.StringValue
		case 5:
			link.AuthKey = root.StringValue
		}
	}

	if link.ShareURL == "" {
		return nil, fmt.Errorf("share URL not found in API response")
	}

	return link, nil
}

// MoveToTrash moves media to trash using its deduplication key.
func (c *Client) MoveToTrash(ctx context.Context, dedupKey string) error {
	cleanKey := strings.TrimSpace(dedupKey)
	if cleanKey == "" {
		return fmt.Errorf("dedupKey cannot be empty")
	}

	payload := BuildTrashPayload([]string{cleanKey})
	_, err := c.sendRequest(ctx, endpointDeletePermanent, payload)
	if err != nil {
		return fmt.Errorf("MoveToTrash failed: %w", err)
	}
	return nil
}

// DeletePermanently deletes media permanently using its deduplication key (SHA-1 urlsafe base64).
func (c *Client) DeletePermanently(ctx context.Context, dedupKey string) error {
	cleanKey := strings.TrimSpace(dedupKey)
	if cleanKey == "" {
		return fmt.Errorf("dedupKey cannot be empty")
	}

	payload := BuildDeletePermanentlyPayload([]string{cleanKey})
	_, err := c.sendRequest(ctx, endpointDeletePermanent, payload)
	if err != nil {
		return fmt.Errorf("DeletePermanently failed: %w", err)
	}
	return nil
}

// DeleteByMediaKey resolves the dedupKey from the mediaKey, moves to trash, and permanently deletes it.
func (c *Client) DeleteByMediaKey(ctx context.Context, mediaKey string) error {
	info, err := c.GetDownloadURL(ctx, mediaKey)
	if err != nil {
		return fmt.Errorf("failed to resolve media info for deletion: %w", err)
	}
	if info.DedupKey == "" {
		return fmt.Errorf("could not determine dedupKey for media %s", mediaKey)
	}

	// First move to trash (Google Photos requires item in trash before permanent deletion)
	_ = c.MoveToTrash(ctx, info.DedupKey)

	// Then permanently delete
	return c.DeletePermanently(ctx, info.DedupKey)
}

// ImportSharedMedia imports shared photos/videos into the user's Google Photos account.
func (c *Client) ImportSharedMedia(ctx context.Context, mediaKeys []string, authKey, albumKey string) (*SaveResult, error) {
	if len(mediaKeys) == 0 {
		return nil, fmt.Errorf("mediaKeys cannot be empty")
	}

	payload := BuildSavePayload(mediaKeys, authKey, albumKey)
	respBytes, err := c.sendRequest(ctx, endpointSaveImport, payload)
	if err != nil {
		return nil, fmt.Errorf("ImportSharedMedia failed: %w", err)
	}

	nodes, err := ParseProtobuf(respBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to decode ImportSharedMedia response: %w", err)
	}

	result := &SaveResult{
		OriginalKeys: mediaKeys,
	}

	for _, root := range nodes {
		// Field 1: list of newly created media items in account
		if root.FieldNum == 1 {
			for _, item := range root.FindAllChildren(1) {
				if itemKeyNode := item.FindFirstChild(1); itemKeyNode != nil && itemKeyNode.StringValue != "" {
					result.NewKeys = append(result.NewKeys, itemKeyNode.StringValue)
				}
			}
			// Single item case
			if len(result.NewKeys) == 0 {
				if itemKeyNode := root.FindFirstChild(1); itemKeyNode != nil && itemKeyNode.StringValue != "" {
					result.NewKeys = append(result.NewKeys, itemKeyNode.StringValue)
				}
			}
		}

		// Field 3: status code (2 = success)
		if root.FieldNum == 3 {
			result.Status = int(root.VarintValue)
		}
	}

	return result, nil
}

// FindMediaByHash checks if a file with the given SHA-1 hash already exists in the library.
func (c *Client) FindMediaByHash(ctx context.Context, sha1Bytes []byte) (*ExistResult, error) {
	if len(sha1Bytes) != 20 {
		return nil, fmt.Errorf("SHA-1 hash must be exactly 20 bytes, got %d", len(sha1Bytes))
	}

	payload := BuildFindByHashPayload(sha1Bytes)
	respBytes, err := c.sendRequest(ctx, endpointFindByHash, payload)
	if err != nil {
		return nil, fmt.Errorf("FindMediaByHash failed: %w", err)
	}

	nodes, err := ParseProtobuf(respBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to decode FindMediaByHash response: %w", err)
	}

	res := &ExistResult{Exists: false}
	for _, root := range nodes {
		if root.FieldNum == 1 {
			if f2 := root.FindFirstChild(2); f2 != nil {
				if inner2 := f2.FindFirstChild(2); inner2 != nil {
					if f1 := inner2.FindFirstChild(1); f1 != nil && f1.StringValue != "" {
						res.Exists = true
						res.MediaKey = f1.StringValue
						return res, nil
					}
				}
			}
		}
	}

	return res, nil
}

func urlSafeBase64(b []byte) string {
	encoded := base64.StdEncoding.EncodeToString(b)
	encoded = strings.ReplaceAll(encoded, "+", "-")
	encoded = strings.ReplaceAll(encoded, "/", "_")
	return strings.TrimRight(encoded, "=")
}
