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
	OriginalKeys  []string `json:"original_keys"`
	NewKeys       []string `json:"new_keys"`
	Status        int      `json:"status"`
	StatusMessage string   `json:"status_message,omitempty"`
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

// CookieStatus represents the validation state of Google cookies.
type CookieStatus struct {
	Valid   bool   `json:"valid"`
	Account string `json:"account,omitempty"`
	Message string `json:"message,omitempty"`
}

// DriveImportResult represents the result of importing a Google Drive file to Google Photos.
type DriveImportResult struct {
	DriveFileID string `json:"drive_file_id"`
	MediaKey    string `json:"media_key"`
	DedupKey    string `json:"dedup_key"`
	DownloadURL string `json:"download_url,omitempty"`
}

// ScrapedShare contains metadata parsed from a public Google Photos share link.
type ScrapedShare struct {
	ShareURL  string   `json:"share_url"`
	AlbumKey  string   `json:"album_key"`
	AuthKey   string   `json:"auth_key"`
	MediaKeys []string `json:"media_keys"`
}

// StorageQuota contains Google account storage usage and quota limits.
type StorageQuota struct {
	UsageText    string  `json:"usage_text"`    // e.g. "9.3 GB of 15 GB used"
	UsedDisplay  string  `json:"used_display"`  // e.g. "9.3 GB"
	TotalDisplay string  `json:"total_display"` // e.g. "15 GB"
	UsedPercent  float64 `json:"used_percent"`  // e.g. 61.7
	FreePercent  float64 `json:"free_percent"`  // e.g. 38.3
	UsedBytes    int64   `json:"used_bytes"`    // in bytes
	TotalBytes   int64   `json:"total_bytes"`   // in bytes
}

// DriveBatchItem represents an individual Google Drive file to import.
type DriveBatchItem struct {
	DriveFileID string `json:"drive_file_id"`
	MimeType    string `json:"mime_type"`
}

// DriveImportItemResult represents the outcome for an individual file in a batch import.
type DriveImportItemResult struct {
	DriveFileID string `json:"drive_file_id"`
	MediaKey    string `json:"media_key"`
	DedupKey    string `json:"dedup_key"`
	DownloadURL string `json:"download_url,omitempty"`
	Width       int    `json:"width,omitempty"`
	Height      int    `json:"height,omitempty"`
	FileSize    int64  `json:"file_size,omitempty"`
	Status      int    `json:"status"`
	Error       string `json:"error,omitempty"`
	RawItem     string `json:"raw_item,omitempty"`
}

// DriveBatchImportResult contains results of batch importing from Google Drive.
type DriveBatchImportResult struct {
	SuccessCount  int                     `json:"success_count"`
	FailedCount   int                     `json:"failed_count"`
	Items         []DriveImportItemResult `json:"items"`
	QuotaExceeded bool                    `json:"quota_exceeded"`
	ErrorMessage  string                  `json:"error_message,omitempty"`
	RawResponse   string                  `json:"raw_response,omitempty"`
}

// AccountResetResult contains details of Google Photos library reset / wipe operation.
type AccountResetResult struct {
	Success      bool   `json:"success"`
	TotalDeleted int    `json:"total_deleted"`
	TrashEmptied bool   `json:"trash_emptied"`
	Message      string `json:"message"`
}
