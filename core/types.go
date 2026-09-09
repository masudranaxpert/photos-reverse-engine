package core

// DownloadInfo contains direct download URLs and file metadata.
type DownloadInfo struct {
	MediaKey    string `json:"media_key"`
	Filename    string `json:"filename"`
	FileSize    int64  `json:"file_size"`
	DownloadURL string `json:"download_url"`
	Sha1Hex     string `json:"sha1_hex"`
	Sha1Bytes   []byte `json:"-"`
	DedupKey    string `json:"dedup_key"`
}

// ShareInfo contains created album and sharing metadata.
type ShareInfo struct {
	AlbumName     string   `json:"album_name"`
	AlbumMediaKey string   `json:"album_media_key"`
	MediaKeys     []string `json:"media_keys"`
}

// SaveResult contains the outcome of an import/save operation.
type SaveResult struct {
	OriginalKeys []string `json:"original_keys"`
	NewKeys      []string `json:"new_keys"`
	Status       int      `json:"status"`
}

// ExistResult contains information about whether a media item already exists.
type ExistResult struct {
	Exists   bool   `json:"exists"`
	MediaKey string `json:"media_key,omitempty"`
}

// PublicShareLink contains the generated public photos.app.goo.gl link and envelope metadata.
type PublicShareLink struct {
	ShareURL    string   `json:"share_url"`
	EnvelopeKey string   `json:"envelope_key"`
	AuthKey     string   `json:"auth_key"`
	MediaKeys   []string `json:"media_keys"`
}
