package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"sync"
	"sync/atomic"
	"unsafe"

	pe "photos_engine"
)

var (
	clientsLock sync.RWMutex
	clientsMap  = make(map[uint64]*pe.Client)
	nextHandle  uint64
)

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
func GPMC_GetToken(handle C.ulonglong) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	token, err := client.GetToken(context.Background())
	return jsonResponse(token, err)
}

//export GPMC_GetDownloadURL
func GPMC_GetDownloadURL(handle C.ulonglong, cMediaKey *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	mediaKey := C.GoString(cMediaKey)
	info, err := client.GetDownloadURL(context.Background(), mediaKey)
	return jsonResponse(info, err)
}

//export GPMC_CreateAlbum
func GPMC_CreateAlbum(handle C.ulonglong, cAlbumName *C.char, cMediaKeysJSON *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	albumName := C.GoString(cAlbumName)
	keysJSON := C.GoString(cMediaKeysJSON)
	var mediaKeys []string
	if err := json.Unmarshal([]byte(keysJSON), &mediaKeys); err != nil {
		return jsonResponse(nil, err)
	}

	info, err := client.CreateAlbum(context.Background(), albumName, mediaKeys)
	return jsonResponse(info, err)
}

//export GPMC_CreateShareLink
func GPMC_CreateShareLink(handle C.ulonglong, cMediaKeysJSON *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	keysJSON := C.GoString(cMediaKeysJSON)
	var mediaKeys []string
	if err := json.Unmarshal([]byte(keysJSON), &mediaKeys); err != nil {
		return jsonResponse(nil, err)
	}

	link, err := client.CreateShareLink(context.Background(), mediaKeys)
	return jsonResponse(link, err)
}

//export GPMC_DeletePermanently
func GPMC_DeletePermanently(handle C.ulonglong, cDedupKey *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	dedupKey := C.GoString(cDedupKey)
	err := client.DeletePermanently(context.Background(), dedupKey)
	return jsonResponse(true, err)
}

//export GPMC_DeleteByMediaKey
func GPMC_DeleteByMediaKey(handle C.ulonglong, cMediaKey *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	mediaKey := C.GoString(cMediaKey)
	err := client.DeleteByMediaKey(context.Background(), mediaKey)
	return jsonResponse(true, err)
}

//export GPMC_ImportSharedMedia
func GPMC_ImportSharedMedia(handle C.ulonglong, cMediaKeysJSON *C.char, cAuthKey *C.char, cAlbumKey *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	keysJSON := C.GoString(cMediaKeysJSON)
	var mediaKeys []string
	if err := json.Unmarshal([]byte(keysJSON), &mediaKeys); err != nil {
		return jsonResponse(nil, err)
	}

	authKey := C.GoString(cAuthKey)
	albumKey := C.GoString(cAlbumKey)

	res, err := client.ImportSharedMedia(context.Background(), mediaKeys, authKey, albumKey)
	return jsonResponse(res, err)
}

//export GPMC_FindMediaByHash
func GPMC_FindMediaByHash(handle C.ulonglong, cSha1Hex *C.char) *C.char {
	client := getClient(uint64(handle))
	if client == nil {
		return jsonResponse(nil, nil)
	}
	sha1Hex := C.GoString(cSha1Hex)
	sha1Bytes, err := hex.DecodeString(sha1Hex)
	if err != nil {
		return jsonResponse(nil, err)
	}

	res, err := client.FindMediaByHash(context.Background(), sha1Bytes)
	return jsonResponse(res, err)
}

//export GPMC_FreeString
func GPMC_FreeString(str *C.char) {
	C.free(unsafe.Pointer(str))
}

func main() {}
