package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sync"
	"sync/atomic"
	"time"
	"unsafe"

	pe "github.com/masudranaxpert/photos-reverse-engine/core"
)

var (
	clientsLock    sync.RWMutex
	clientsMap     = make(map[uint64]*pe.Client)
	nextHandle     uint64

	webClientsLock sync.RWMutex
	webClientsMap  = make(map[uint64]*pe.WebClient)
	nextWebHandle  uint64
)

func registerWebClient(c *pe.WebClient) uint64 {
	h := atomic.AddUint64(&nextWebHandle, 1)
	webClientsLock.Lock()
	webClientsMap[h] = c
	webClientsLock.Unlock()
	return h
}

func getWebClient(handle uint64) *pe.WebClient {
	webClientsLock.RLock()
	defer webClientsLock.RUnlock()
	return webClientsMap[handle]
}

func registerClient(c *pe.Client) uint64 {
	h := atomic.AddUint64(&nextHandle, 1)
	clientsLock.Lock()
	clientsMap[h] = c
	clientsLock.Unlock()
	return h
}

func getClient(handle uint64) *pe.Client {
	clientsLock.RLock()
	defer clientsLock.RUnlock()
	return clientsMap[handle]
}

func getContext(timeoutMs C.longlong) (context.Context, context.CancelFunc) {
	ms := int64(timeoutMs)
	if ms <= 0 {
		ms = 45000 // default 45 seconds fallback
	}
	return context.WithTimeout(context.Background(), time.Duration(ms)*time.Millisecond)
}

func jsonResponse(data interface{}, err error) *C.char {
	type resp struct {
		Success bool        `json:"success"`
		Data    interface{} `json:"data,omitempty"`
		Error   string      `json:"error,omitempty"`
	}

	r := resp{
		Success: err == nil,
		Data:    data,
	}
	if err != nil {
		r.Error = err.Error()
	}

	b, _ := json.Marshal(r)
	return C.CString(string(b))
}

//export GPMC_CreateClient
func GPMC_CreateClient(cAuthData *C.char) *C.char {
	authData := C.GoString(cAuthData)
	client, err := pe.NewClient(authData)
	if err != nil {
		return jsonResponse(nil, err)
	}
	h := registerClient(client)
	return jsonResponse(map[string]interface{}{"handle": h}, nil)
}

//export GPMC_NewClient
func GPMC_NewClient(cAuthData *C.char) C.ulonglong {
	authData := C.GoString(cAuthData)
	client, err := pe.NewClient(authData)
	if err != nil {
		return 0
	}
	return C.ulonglong(registerClient(client))
}

//export GPMC_CloseClient
func GPMC_CloseClient(handle C.ulonglong) {
	clientsLock.Lock()
	delete(clientsMap, uint64(handle))
	clientsLock.Unlock()
}

//export GPMC_GetToken
func GPMC_GetToken(handle C.ulonglong, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	token, err := client.GetToken(ctx)
	return jsonResponse(token, err)
}

//export GPMC_GetDownloadURL
func GPMC_GetDownloadURL(handle C.ulonglong, cMediaKey *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	mediaKey := C.GoString(cMediaKey)
	info, err := client.GetDownloadURL(ctx, mediaKey)
	return jsonResponse(info, err)
}

//export GPMC_CreateAlbum
func GPMC_CreateAlbum(handle C.ulonglong, cAlbumName *C.char, cMediaKeysJSON *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	keysJSON := C.GoString(cMediaKeysJSON)
	var mediaKeys []string
	if err := json.Unmarshal([]byte(keysJSON), &mediaKeys); err != nil {
		return jsonResponse(nil, err)
	}
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	albumName := C.GoString(cAlbumName)
	info, err := client.CreateAlbum(ctx, albumName, mediaKeys)
	return jsonResponse(info, err)
}

//export GPMC_CreateShareLink
func GPMC_CreateShareLink(handle C.ulonglong, cMediaKeysJSON *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	keysJSON := C.GoString(cMediaKeysJSON)
	var mediaKeys []string
	if err := json.Unmarshal([]byte(keysJSON), &mediaKeys); err != nil {
		return jsonResponse(nil, err)
	}
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	link, err := client.CreateShareLink(ctx, mediaKeys)
	return jsonResponse(link, err)
}

//export GPMC_DeletePermanently
func GPMC_DeletePermanently(handle C.ulonglong, cDedupKey *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	dedupKey := C.GoString(cDedupKey)
	err := client.DeletePermanently(ctx, dedupKey)
	return jsonResponse(true, err)
}

//export GPMC_DeleteByMediaKey
func GPMC_DeleteByMediaKey(handle C.ulonglong, cMediaKey *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	mediaKey := C.GoString(cMediaKey)
	err := client.DeleteByMediaKey(ctx, mediaKey)
	return jsonResponse(true, err)
}

//export GPMC_ImportSharedMedia
func GPMC_ImportSharedMedia(handle C.ulonglong, cMediaKeysJSON *C.char, cAuthKey *C.char, cAlbumKey *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	keysJSON := C.GoString(cMediaKeysJSON)
	var mediaKeys []string
	if err := json.Unmarshal([]byte(keysJSON), &mediaKeys); err != nil {
		return jsonResponse(nil, err)
	}
	authKey := C.GoString(cAuthKey)
	albumKey := C.GoString(cAlbumKey)

	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	res, err := client.ImportSharedMedia(ctx, mediaKeys, authKey, albumKey)
	return jsonResponse(res, err)
}

//export GPMC_FindMediaByHash
func GPMC_FindMediaByHash(handle C.ulonglong, cSha1Hex *C.char, timeoutMs C.longlong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	sha1Hex := C.GoString(cSha1Hex)
	sha1Bytes, err := hex.DecodeString(sha1Hex)
	if err != nil {
		return jsonResponse(nil, err)
	}

	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	res, err := client.FindMediaByHash(ctx, sha1Bytes)
	return jsonResponse(res, err)
}

//export GPWC_CreateClient
func GPWC_CreateClient(cCookieData *C.char) *C.char {
	raw := C.GoString(cCookieData)
	cookie, err := pe.ParseCookies(raw)
	if err != nil {
		return jsonResponse(nil, err)
	}
	client, err := pe.NewWebClient(cookie)
	if err != nil {
		return jsonResponse(nil, err)
	}
	h := registerWebClient(client)
	return jsonResponse(map[string]interface{}{"handle": h}, nil)
}

//export GPWC_NewClient
func GPWC_NewClient(cCookieData *C.char) C.ulonglong {
	raw := C.GoString(cCookieData)
	cookie, err := pe.ParseCookies(raw)
	if err != nil {
		return 0
	}
	client, err := pe.NewWebClient(cookie)
	if err != nil {
		return 0
	}
	return C.ulonglong(registerWebClient(client))
}

//export GPWC_CreateClientFromBlob
func GPWC_CreateClientFromBlob(cBlobHex *C.char) *C.char {
	blobHex := C.GoString(cBlobHex)
	blob, err := hex.DecodeString(blobHex)
	if err != nil {
		return jsonResponse(nil, err)
	}
	client, err := pe.NewWebClientFromBlob(blob)
	if err != nil {
		return jsonResponse(nil, err)
	}
	h := registerWebClient(client)
	return jsonResponse(map[string]interface{}{"handle": h}, nil)
}

//export GPWC_ExportSessionBlob
func GPWC_ExportSessionBlob(handle C.ulonglong) *C.char {
	client := getWebClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("web client handle not found"))
	}
	blob, err := client.MarshalSession()
	if err != nil {
		return jsonResponse(nil, err)
	}
	return jsonResponse(map[string]interface{}{"blob_hex": hex.EncodeToString(blob)}, nil)
}

//export GPWC_ExportCookies
func GPWC_ExportCookies(handle C.ulonglong) *C.char {
	client := getWebClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("web client handle not found"))
	}
	cookies := client.GetCookies()
	return jsonResponse(map[string]interface{}{
		"header":   cookies.BuildCookieHeader(),
		"netscape": cookies.ToNetscape(),
	}, nil)
}

//export GPWC_CloseClient
func GPWC_CloseClient(handle C.ulonglong) {
	webClientsLock.Lock()
	delete(webClientsMap, uint64(handle))
	webClientsLock.Unlock()
}

//export GPWC_CheckStatus
func GPWC_CheckStatus(cCookieData *C.char) *C.char {
	raw := C.GoString(cCookieData)
	cookie, err := pe.ParseCookies(raw)
	if err != nil {
		return jsonResponse(nil, err)
	}
	status, err := pe.CheckCookieStatus(cookie)
	return jsonResponse(status, err)
}

//export GPWC_GetDownloadURL
func GPWC_GetDownloadURL(handle C.ulonglong, cMediaKey *C.char) *C.char {
	client := getWebClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	mediaKey := C.GoString(cMediaKey)
	info, err := client.GetDownloadURL(mediaKey)
	return jsonResponse(info, err)
}

//export GPWC_ImportFromDrive
func GPWC_ImportFromDrive(handle C.ulonglong, cDriveID *C.char, cMimeType *C.char, cleanup C.int) *C.char {
	client := getWebClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	driveID := C.GoString(cDriveID)
	mimeType := C.GoString(cMimeType)
	result, err := client.ImportFromDrive(driveID, mimeType, cleanup != 0)
	return jsonResponse(result, err)
}

//export GPWC_CreateShareLink
func GPWC_CreateShareLink(handle C.ulonglong, cMediaKey *C.char) *C.char {
	client := getWebClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	mediaKey := C.GoString(cMediaKey)
	link, err := client.CreateShareLink(mediaKey)
	return jsonResponse(link, err)
}

//export GPWC_GetStorageQuota
func GPWC_GetStorageQuota(handle C.ulonglong) *C.char {
	client := getWebClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, errors.New("client handle not found"))
	}
	quota, err := client.GetStorageQuota()
	return jsonResponse(quota, err)
}


//export GPMC_ScrapeShareURL
func GPMC_ScrapeShareURL(cURL *C.char, timeoutMs C.longlong) *C.char {
	targetURL := C.GoString(cURL)
	ctx, cancel := getContext(timeoutMs)
	defer cancel()
	res, err := pe.ScrapeShareURL(ctx, targetURL)
	return jsonResponse(res, err)
}

//export GPMC_FreeString
func GPMC_FreeString(str *C.char) {
	C.free(unsafe.Pointer(str))
}

func main() {}
