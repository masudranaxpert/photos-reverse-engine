package core

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestScrapeShareURL(t *testing.T) {
	mockHTML := `
<!DOCTYPE html>
<html>
<head><title>Photos</title></head>
<body>
  <a href="./share/AF1QipMockAlbumKey?key=mockAuthKey123">Album</a>
  <a href="./photo/AF1QipMediaKeyOne?key=mockAuthKey123">Photo 1</a>
  <a href="./photo/AF1QipMediaKeyTwo">Photo 2</a>
  <script>
    window.WIZ_global_data = {
      "data": [null, [["AF1QipMediaKeyThree"]], null, ["AF1QipMockAlbumKey", null, null, null, null, null, null, null, null, null, null, null, null, null, "mockAuthKey123"]],
      sideChannel: {}
    };
  </script>
</body>
</html>
`

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(mockHTML))
	}))
	defer server.Close()

	targetURL := server.URL + "/share/AF1QipMockAlbumKey?key=mockAuthKey123"
	res, err := ScrapeShareURL(context.Background(), targetURL)
	if err != nil {
		t.Fatalf("ScrapeShareURL returned unexpected error: %v", err)
	}

	if res.AlbumKey != "AF1QipMockAlbumKey" {
		t.Errorf("expected album key 'AF1QipMockAlbumKey', got '%s'", res.AlbumKey)
	}
	if res.AuthKey != "mockAuthKey123" {
		t.Errorf("expected auth key 'mockAuthKey123', got '%s'", res.AuthKey)
	}
	if len(res.MediaKeys) < 2 {
		t.Fatalf("expected at least 2 media keys, got %d: %v", len(res.MediaKeys), res.MediaKeys)
	}
	if res.MediaKeys[0] != "AF1QipMediaKeyOne" || res.MediaKeys[1] != "AF1QipMediaKeyTwo" {
		t.Errorf("unexpected media keys: %v", res.MediaKeys)
	}
}
