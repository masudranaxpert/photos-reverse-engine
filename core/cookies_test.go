package core

import (
	"strings"
	"testing"

	"github.com/sardanioss/httpcloak"
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

	if cookie.Get("SID") != "test_sid" {
		t.Errorf("expected SID test_sid, got %s", cookie.Get("SID"))
	}
	if cookie.Get("__Secure-1PSID") != "test_psid" {
		t.Errorf("expected Secure1PSID test_psid, got %s", cookie.Get("__Secure-1PSID"))
	}
	if cookie.Get("__Secure-1PSIDTS") != "test_ts" {
		t.Errorf("expected Secure1PSIDTS test_ts, got %s", cookie.Get("__Secure-1PSIDTS"))
	}
	if cookie.Get("OSID") != "test_osid" {
		t.Errorf("expected OSID test_osid, got %s", cookie.Get("OSID"))
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

	if cookie.Get("SID") != "json_sid" || cookie.Get("__Secure-1PSID") != "json_psid" {
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

	if cookie.Get("SID") != "space_sid" || cookie.Get("__Secure-1PSID") != "space_psid" {
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

func TestFullUnfilteredCookies(t *testing.T) {
	raw := "SID=sid_val; __Secure-1PSID=psid_val; SAPISID=sapi_val; APISID=api_val; SSID=ssid_val; HSID=hsid_val; __Secure-3PSID=3psid_val; LOGIN_INFO=login_val"
	cookie, err := ParseCookies(raw)
	if err != nil {
		t.Fatalf("ParseCookies failed: %v", err)
	}

	if cookie.Get("SAPISID") != "sapi_val" {
		t.Errorf("expected SAPISID sapi_val, got %s", cookie.Get("SAPISID"))
	}
	if cookie.Get("LOGIN_INFO") != "login_val" {
		t.Errorf("expected LOGIN_INFO login_val, got %s", cookie.Get("LOGIN_INFO"))
	}

	header := cookie.BuildCookieHeader()
	for _, expected := range []string{"SID=sid_val", "SAPISID=sapi_val", "APISID=api_val", "LOGIN_INFO=login_val"} {
		if !strings.Contains(header, expected) {
			t.Errorf("expected header to contain %q, but got: %s", expected, header)
		}
	}
}

func TestHttpcloakSession(t *testing.T) {
	s := httpcloak.NewSession("firefox-latest", httpcloak.WithoutRedirects())
	defer s.Close()

	s.SetCookie(httpcloak.CookieInfo{
		Name:   "SID",
		Value:  "test_sid",
		Domain: ".google.com",
		Path:   "/",
		Secure: true,
	})

	cookies := s.GetCookies()
	if len(cookies) == 0 {
		t.Error("expected at least 1 cookie")
	}

	blob, err := s.Marshal()
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}
	if len(blob) == 0 {
		t.Error("expected non-empty blob")
	}

	s2, err := httpcloak.UnmarshalSession(blob)
	if err != nil {
		t.Fatalf("UnmarshalSession failed: %v", err)
	}
	defer s2.Close()

	if len(s2.GetCookies()) == 0 {
		t.Error("expected restored session to have cookies")
	}

	// Verify scraper session preset (chrome-latest)
	sChrome := httpcloak.NewSession("chrome-latest", httpcloak.WithoutRedirects())
	defer sChrome.Close()
	if sChrome == nil {
		t.Error("expected valid chrome-latest session")
	}
}

func TestParseStorageQuotaHTML(t *testing.T) {
	snippet := `
<div class="XCxRFf" style="width:61.7%;"></div>
<div class="DFG23b" style="width:38.3%;"></div>
</div>
<div class="nXkqdd"><a class="zWKF8d" jscontroller="XC0hee" jsaction="click:RySO6d;" href="./quotamanagement" data-location="11" jslog="60969; track:click">9.3 GB of 15 GB used</a></div>
</div>
<div jscontroller="HRlsHd" jsaction="S2Nv3c:fJTaH"></div>
</div><c-data id="i13" jsdata="`

	quota, err := parseStorageQuotaHTML(snippet)
	if err != nil {
		t.Fatalf("parseStorageQuotaHTML failed: %v", err)
	}

	if quota.UsageText != "9.3 GB of 15 GB used" {
		t.Errorf("expected '9.3 GB of 15 GB used', got '%s'", quota.UsageText)
	}
	if quota.UsedDisplay != "9.3 GB" {
		t.Errorf("expected '9.3 GB', got '%s'", quota.UsedDisplay)
	}
	if quota.TotalDisplay != "15 GB" {
		t.Errorf("expected '15 GB', got '%s'", quota.TotalDisplay)
	}
	if quota.UsedPercent != 61.7 {
		t.Errorf("expected 61.7, got %f", quota.UsedPercent)
	}
	if quota.FreePercent != 38.3 {
		t.Errorf("expected 38.3, got %f", quota.FreePercent)
	}
	if quota.TotalBytes <= 0 || quota.UsedBytes <= 0 {
		t.Errorf("expected positive byte values, got used=%d, total=%d", quota.UsedBytes, quota.TotalBytes)
	}
}

func TestParseBatchexecuteErrors(t *testing.T) {
	// 1. Quota exceeded payload (User sample 2)
	quotaErrPayload := `)]}'

202
[["wrb.fr","SusGud",null,null,null,[8,null,[["type.googleapis.com/social.frontend.photos.data.PhotosWebImportDriveItemsFailure",[1]]]],"generic"],["di",266],["af.httprm",265,"6924186633903814306",28]]
25
[["e",4,null,null,238]]`

	_, err := parseBatchexecuteEnvelope(quotaErrPayload, "SusGud")
	if err == nil {
		t.Fatal("expected error for quota exceeded payload, got nil")
	}
	if !strings.Contains(err.Error(), "STORAGE_QUOTA_EXCEEDED") {
		t.Errorf("expected STORAGE_QUOTA_EXCEEDED in error message, got: %v", err)
	}

	// 2. Timeout payload (User sample 1)
	timeoutPayload := `)]}'

111
[["wrb.fr","SusGud",null,null,null,[13],"generic"],["di",30081],["af.httprm",30081,"4257157892430432481",47]]
25
[["e",4,null,null,147]]`

	_, err2 := parseBatchexecuteEnvelope(timeoutPayload, "SusGud")
	if err2 == nil {
		t.Fatal("expected error for timeout payload, got nil")
	}
	if !strings.Contains(err2.Error(), "RPC_TIMEOUT") {
		t.Errorf("expected RPC_TIMEOUT in error message, got: %v", err2)
	}
}

func TestParseSusGudBatchSuccess(t *testing.T) {
	// User sample 3: Multi-item success response
	successPayload := `)]}'

1241
[["wrb.fr","SusGud","[[[\"173o1kBve_RiXmI2ECCrfgRT91KG62Mz3\",[\"AF1QipMjDY09Q2fyOLRqbT9n67ChqorvTboeE2CeuYqP\",[\"https://photos.fife.usercontent.google.com/pw/AP1GczOyO4bSxduAfPJi-2iM1FLM2v-wK3lkquFc5aJA5iwXNz1FQniGh5PH\",1920,960],1760683961882,\"QleyGUKTgeHhG39OwuYv-JftvYM\",21600000,1789024049822,null,null,2,{\"15\":2128,\"76647426\":[7056840,null,null,null,null,3,null,null,null,false]}],0],[\"1TjQP3B7gw1tEkNPJbmalIbYDVWlxggXH\",[\"AF1QipM29VPaagOBq3zW_IMTith5S-oOVSKvuW2PUFyu\",[\"https://photos.fife.usercontent.google.com/pw/AP1GczMxU8CF5mElNNe28F67HV4Gi6dAVE72-HsjKmQR7A0xb4gdFlP7ChqH\",1920,1080],1786949954936,\"fU6BFiqfkEE9Aa9TU7Vrh6O3J0g\",21600000,1789024049822,null,null,2,{\"15\":2128,\"76647426\":[13192743,null,null,null,null,3,null,null,null,false]}],0],[\"1H2E0dwhZlBfE2xNNZwN2nkhvUgyLZIVm\",[\"AF1QipNUzSFcxjys2rSaFpqS0vBxcW82Mw2icDhvZM1G\",[\"https://photos.fife.usercontent.google.com/pw/AP1GczMO1EJFSbr_1TuiK3v7TmALQN7uDk10nuetQKaSaj30cfQ1en_3bzuP\",720,300],1787855146041,\"CW5DDh5Ec7PpdmgS0gA5cQCVE_U\",21600000,1789024049822,null,null,2,{\"15\":2128,\"76647426\":[11054270,null,null,null,null,3,null,null,null,false]}],0]]]",null,null,null,"generic"],["di",2250],["af.httprm",2250,"-7729581887131103621",29]]
26
[["e",4,null,null,1279]]`

	respData, err := parseBatchexecuteEnvelope(successPayload, "SusGud")
	if err != nil {
		t.Fatalf("parseBatchexecuteEnvelope failed: %v", err)
	}

	itemsArr := safeGetIndex(respData, 0)
	list, ok := itemsArr.([]interface{})
	if !ok {
		t.Fatalf("expected []interface{} for itemsArr, got %T", itemsArr)
	}

	if len(list) != 3 {
		t.Fatalf("expected 3 items, got %d", len(list))
	}

	// First item check
	it0 := list[0].([]interface{})
	driveID0 := it0[0].(string)
	if driveID0 != "173o1kBve_RiXmI2ECCrfgRT91KG62Mz3" {
		t.Errorf("expected driveID 173o1kBve_RiXmI2ECCrfgRT91KG62Mz3, got %s", driveID0)
	}
	meta0 := it0[1].([]interface{})
	mediaKey0 := meta0[0].(string)
	if mediaKey0 != "AF1QipMjDY09Q2fyOLRqbT9n67ChqorvTboeE2CeuYqP" {
		t.Errorf("expected mediaKey AF1QipMjDY09Q2fyOLRqbT9n67ChqorvTboeE2CeuYqP, got %s", mediaKey0)
	}
	url0 := meta0[1].([]interface{})[0].(string)
	if !strings.HasPrefix(url0, "https://photos.fife.usercontent.google.com") {
		t.Errorf("expected fife url, got %s", url0)
	}
	w0 := int(meta0[1].([]interface{})[1].(float64))
	h0 := int(meta0[1].([]interface{})[2].(float64))
	if w0 != 1920 || h0 != 960 {
		t.Errorf("expected 1920x960, got %dx%d", w0, h0)
	}
	dedup0 := meta0[3].(string)
	if dedup0 != "QleyGUKTgeHhG39OwuYv-JftvYM" {
		t.Errorf("expected dedup key QleyGUKTgeHhG39OwuYv-JftvYM, got %s", dedup0)
	}
}

func TestParseSusGudUnsupportedFormat(t *testing.T) {
	// Status 3 payload: Google Photos rejects non-media files (e.g. .rar, .zip)
	unsupportedPayload := `)]}'

72
[["wrb.fr","SusGud","[[[\"1NNVzoBzBeAg4FIOPijqJHkgxWJPxBtC7\",null,3]]]",null,null,null,"generic"],["di",1234],["af.httprm",1234,"-1234567890",10]]`

	respData, err := parseBatchexecuteEnvelope(unsupportedPayload, "SusGud")
	if err != nil {
		t.Fatalf("parseBatchexecuteEnvelope failed: %v", err)
	}

	itemsArr := safeGetIndex(respData, 0)
	list, ok := itemsArr.([]interface{})
	if !ok || len(list) != 1 {
		t.Fatalf("expected 1 item in list, got %v", itemsArr)
	}

	it := list[0].([]interface{})
	driveID := it[0].(string)
	if driveID != "1NNVzoBzBeAg4FIOPijqJHkgxWJPxBtC7" {
		t.Errorf("expected driveID 1NNVzoBzBeAg4FIOPijqJHkgxWJPxBtC7, got %s", driveID)
	}
	if it[1] != nil {
		t.Errorf("expected nil metadata for unsupported file, got %v", it[1])
	}
	st := int(it[2].(float64))
	if st != 3 {
		t.Errorf("expected status 3, got %d", st)
	}
}

