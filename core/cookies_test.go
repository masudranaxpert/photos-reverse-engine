package core

import (
	"testing"
)

func TestParseCookiesNetscape(t *testing.T) {
	netscape := `# Netscape HTTP Cookie File
.google.com	TRUE	/	TRUE	1893456000	SID	test_sid
#HttpOnly_.google.com	TRUE	/	TRUE	1893456000	__Secure-1PSID	test_psid
#HttpOnly_.google.com	TRUE	/	TRUE	1893456000	__Secure-1PSIDTS	test_ts
.google.com	TRUE	/	TRUE	1893456000	OSID	test_osid
`

	cookie, err := ParseCookies(netscape)
	if err != nil {
		t.Fatalf("ParseCookies failed: %v", err)
	}

	if cookie.SID != "test_sid" {
		t.Errorf("expected SID test_sid, got %s", cookie.SID)
	}
	if cookie.Secure1PSID != "test_psid" {
		t.Errorf("expected Secure1PSID test_psid, got %s", cookie.Secure1PSID)
	}
	if cookie.Secure1PSIDTS != "test_ts" {
		t.Errorf("expected Secure1PSIDTS test_ts, got %s", cookie.Secure1PSIDTS)
	}
	if cookie.OSID != "test_osid" {
		t.Errorf("expected OSID test_osid, got %s", cookie.OSID)
	}

	header := cookie.BuildCookieHeader()
	if header == "" {
		t.Error("expected non-empty cookie header")
	}
}

func TestParseCookiesJSON(t *testing.T) {
	jsonCookies := `[
		{"name": "SID", "value": "json_sid"},
		{"name": "__Secure-1PSID", "value": "json_psid"},
		{"name": "OSID", "value": "json_osid"}
	]`

	cookie, err := ParseCookies(jsonCookies)
	if err != nil {
		t.Fatalf("ParseCookies JSON failed: %v", err)
	}

	if cookie.SID != "json_sid" || cookie.Secure1PSID != "json_psid" {
		t.Errorf("unexpected cookie values: %+v", cookie)
	}
}

func TestParseCookiesWhitespaceSeparated(t *testing.T) {
	// Copied text with spaces instead of tabs
	spaceSeparated := `# Netscape HTTP Cookie File
.google.com TRUE / TRUE 1893456000 SID space_sid
.google.com TRUE / TRUE 1893456000 __Secure-1PSID space_psid
`
	cookie, err := ParseCookies(spaceSeparated)
	if err != nil {
		t.Fatalf("ParseCookies space-separated failed: %v", err)
	}

	if cookie.SID != "space_sid" || cookie.Secure1PSID != "space_psid" {
		t.Errorf("unexpected cookie values: %+v", cookie)
	}
}

func TestSafeGetIndex(t *testing.T) {
	nested := []interface{}{
		[]interface{}{
			[]interface{}{
				"val0",
				"val1",
			},
		},
	}

	if safeGetIndex(nested, 0, 0, 1) != "val1" {
		t.Errorf("expected val1, got %v", safeGetIndex(nested, 0, 0, 1))
	}
	if safeGetIndex(nested, 0, 99) != nil {
		t.Error("expected nil for out-of-bounds index")
	}
	if safeGetIndex(nil, 0) != nil {
		t.Error("expected nil for nil input")
	}
}

func TestParseBatchexecuteEnvelope(t *testing.T) {
	body := `)]}'
[["wrb.fr","SusGud","[[[\"drive_123\",[\"media_456\",null,null,\"dedup_789\"]]]]",null,null,null,"generic"]]`

	data, err := parseBatchexecuteEnvelope(body, "SusGud")
	if err != nil {
		t.Fatalf("parseBatchexecuteEnvelope failed: %v", err)
	}

	mediaKey := safeGetIndex(data, 0, 0, 1, 0)
	if mediaKey != "media_456" {
		t.Errorf("expected media_456, got %v", mediaKey)
	}
}
