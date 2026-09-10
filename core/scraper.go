package core

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
	"github.com/sardanioss/httpcloak"
)

var (
	albumKeyRegex = regexp.MustCompile(`/share/([^/?]+)`)
	photoKeyRegex = regexp.MustCompile(`/photo/([^/?#"]+)`)
	dataRegex     = regexp.MustCompile(`(?s)data:\s*(\[.*?\])\s*,\s*sideChannel:`)
)

// ScrapeShareURL fetches and extracts album_key, auth_key, and media_keys from a public Google Photos share URL
// using httpcloak for Chrome TLS/HTTP2 fingerprint emulation and goquery for fast CSS DOM parsing.
func ScrapeShareURL(ctx context.Context, targetURL string) (*ScrapedShare, error) {
	cleanURL := strings.TrimSpace(targetURL)
	if cleanURL == "" {
		return nil, errors.New("share URL cannot be empty")
	}

	session := httpcloak.NewSession("chrome-146", httpcloak.WithSessionTimeout(30*time.Second))
	defer session.Close()

	resp, err := session.Get(ctx, cleanURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch share URL: %w", err)
	}
	defer resp.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("share URL returned HTTP %d", resp.StatusCode)
	}

	finalURL := resp.FinalURL
	if finalURL == "" {
		finalURL = cleanURL
	}
	parsedURL, _ := url.Parse(finalURL)

	albumKey := ""
	if parsedURL != nil {
		if m := albumKeyRegex.FindStringSubmatch(parsedURL.Path); len(m) > 1 {
			albumKey = m[1]
		}
	}
	authKey := ""
	if parsedURL != nil {
		authKey = parsedURL.Query().Get("key")
	}

	bodyStr, err := resp.Text()
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	seen := make(map[string]bool)
	var mediaKeys []string

	// 1. Traverse HTML DOM with goquery (jQuery-like CSS selectors)
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(bodyStr))
	if err == nil {
		doc.Find("a[href*=\"/photo/\"]").Each(func(i int, s *goquery.Selection) {
			if href, exists := s.Attr("href"); exists {
				if m := photoKeyRegex.FindStringSubmatch(href); len(m) > 1 {
					key := m[1]
					if strings.HasPrefix(key, "AF1Qip") && !seen[key] {
						seen[key] = true
						mediaKeys = append(mediaKeys, key)
					}
				}
			}
		})
	}

	// 2. Fallback to embedded script payload if DOM traversal yielded no keys
	if m := dataRegex.FindStringSubmatch(bodyStr); len(m) > 1 {
		var data []interface{}
		if err := json.Unmarshal([]byte(m[1]), &data); err == nil {
			if len(data) > 1 {
				if items, ok := data[1].([]interface{}); ok {
					for _, item := range items {
						if itemArr, ok := item.([]interface{}); ok && len(itemArr) > 0 {
							if key, ok := itemArr[0].(string); ok && strings.HasPrefix(key, "AF1Qip") && !seen[key] {
								seen[key] = true
								mediaKeys = append(mediaKeys, key)
							}
						}
					}
				}
			}
			if albumKey == "" && len(data) > 3 {
				if meta, ok := data[3].([]interface{}); ok && len(meta) > 0 {
					if ak, ok := meta[0].(string); ok {
						albumKey = ak
					}
					if authKey == "" && len(meta) > 14 {
						if k, ok := meta[14].(string); ok {
							authKey = k
						}
					}
				}
			}
		}
	}

	return &ScrapedShare{
		ShareURL:  finalURL,
		AlbumKey:  albumKey,
		AuthKey:   authKey,
		MediaKeys: mediaKeys,
	}, nil
}
