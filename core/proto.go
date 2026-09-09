package gpmc

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"unicode/utf8"
)

// Wire types
const (
	wireVarint = 0
	wireFixed64 = 1
	wireLengthDelimited = 2
	wireFixed32 = 5
)

func encodeVarint(v uint64) []byte {
	var buf []byte
	for v >= 0x80 {
		buf = append(buf, byte(v)|0x80)
		v >>= 7
	}
	buf = append(buf, byte(v))
	return buf
}

func encodeTag(fieldNum int, wireType int) []byte {
	return encodeVarint(uint64((fieldNum << 3) | wireType))
}

func encodeLengthDelimited(fieldNum int, data []byte) []byte {
	var buf []byte
	buf = append(buf, encodeTag(fieldNum, wireLengthDelimited)...)
	buf = append(buf, encodeVarint(uint64(len(data)))...)
	buf = append(buf, data...)
	return buf
}

func encodeString(fieldNum int, s string) []byte {
	return encodeLengthDelimited(fieldNum, []byte(s))
}

func encodeInt(fieldNum int, v int64) []byte {
	var buf []byte
	buf = append(buf, encodeTag(fieldNum, wireVarint)...)
	buf = append(buf, encodeVarint(uint64(v))...)
	return buf
}

// ProtoNode represents a decoded Protobuf field.
type ProtoNode struct {
	FieldNum int
	WireType int
	VarintValue uint64
	BytesValue  []byte
	StringValue string
	Children    []*ProtoNode
}

// ParseProtobuf parses raw bytes into a tree of ProtoNode.
func ParseProtobuf(data []byte) ([]*ProtoNode, error) {
	var nodes []*ProtoNode
	idx := 0

	for idx < len(data) {
		tagByte, n := decodeVarint(data[idx:])
		if n <= 0 {
			break
		}
		idx += n

		fieldNum := int(tagByte >> 3)
		wireType := int(tagByte & 7)

		node := &ProtoNode{
			FieldNum: fieldNum,
			WireType: wireType,
		}

		switch wireType {
		case wireVarint:
			val, n := decodeVarint(data[idx:])
			if n <= 0 {
				return nodes, fmt.Errorf("malformed varint at offset %d", idx)
			}
			idx += n
			node.VarintValue = val

		case wireFixed64:
			if idx+8 > len(data) {
				return nodes, fmt.Errorf("unexpected EOF reading fixed64")
			}
			node.BytesValue = data[idx : idx+8]
			idx += 8

		case wireLengthDelimited:
			length, n := decodeVarint(data[idx:])
			if n <= 0 {
				return nodes, fmt.Errorf("malformed length delimiter at offset %d", idx)
			}
			idx += n
			if idx+int(length) > len(data) {
				return nodes, fmt.Errorf("length %d exceeds remaining buffer", length)
			}
			chunk := data[idx : idx+int(length)]
			idx += int(length)
			node.BytesValue = chunk

			// Try recursive parse
			if len(chunk) > 0 {
				if children, err := ParseProtobuf(chunk); err == nil && len(children) > 0 {
					// Verify all bytes were consumed
					reconstructedLen := 0
					for _, c := range children {
						if c.FieldNum > 0 && c.FieldNum < 10000 {
							reconstructedLen++
						}
					}
					if reconstructedLen > 0 {
						node.Children = children
					}
				}
			}

			if utf8.Valid(chunk) && isPrintable(string(chunk)) {
				node.StringValue = string(chunk)
			}

		case wireFixed32:
			if idx+4 > len(data) {
				return nodes, fmt.Errorf("unexpected EOF reading fixed32")
			}
			node.BytesValue = data[idx : idx+4]
			idx += 4

		default:
			return nodes, fmt.Errorf("unsupported wire type %d", wireType)
		}

		nodes = append(nodes, node)
	}

	return nodes, nil
}

func decodeVarint(data []byte) (uint64, int) {
	var val uint64
	var shift uint
	for i, b := range data {
		if i >= 10 {
			return 0, -1
		}
		val |= uint64(b&0x7F) << shift
		if (b & 0x80) == 0 {
			return val, i + 1
		}
		shift += 7
	}
	return 0, -1
}

func isPrintable(s string) bool {
	if len(s) == 0 {
		return false
	}
	for _, r := range s {
		if r < 32 && r != '\t' && r != '\n' && r != '\r' {
			return false
		}
	}
	return true
}

// FindFirstChild searches for the first child with a specific field number.
func (n *ProtoNode) FindFirstChild(fieldNum int) *ProtoNode {
	for _, child := range n.Children {
		if child.FieldNum == fieldNum {
			return child
		}
	}
	return nil
}

// FindAllChildren searches for all children with a specific field number.
func (n *ProtoNode) FindAllChildren(fieldNum int) []*ProtoNode {
	var res []*ProtoNode
	for _, child := range n.Children {
		if child.FieldNum == fieldNum {
			res = append(res, child)
		}
	}
	return res
}

// BuildSavePayload constructs the exact binary payload for importing photos.
func BuildSavePayload(mediaKeys []string, authKey, albumKey string) []byte {
	var buf bytes.Buffer

	// Field 1: repeated media_key
	for _, mk := range mediaKeys {
		buf.Write(encodeString(1, mk))
	}

	// Field 2: auth_key
	buf.Write(encodeString(2, authKey))

	// Field 3: album_key
	buf.Write(encodeString(3, albumKey))

	// Field 4: { 1: 3 }
	f4 := encodeInt(1, 3)
	buf.Write(encodeLengthDelimited(4, f4))

	// Field 5: { 3: "Pixel XL", 4: "Google", 5: 28 }
	var f5 bytes.Buffer
	f5.Write(encodeString(3, "Pixel XL"))
	f5.Write(encodeString(4, "Google"))
	f5.Write(encodeInt(5, 28))
	buf.Write(encodeLengthDelimited(5, f5.Bytes()))

	return buf.Bytes()
}

// BuildDownloadPayload constructs the payload for PhotosPrepareDownload.
func BuildDownloadPayload(mediaKey string) []byte {
	var buf bytes.Buffer

	// Field 1: { 1: { 1: mediaKey } }
	f1_1 := encodeString(1, mediaKey)
	f1 := encodeLengthDelimited(1, f1_1)
	buf.Write(encodeLengthDelimited(1, f1))

	// Field 2:
	//   1: { 7: { 2: {} } }
	//   5: { 2: {}, 3: {}, 5: { 1: {}, 3: 0 } }
	var f2 bytes.Buffer

	f7 := encodeLengthDelimited(2, []byte{})
	f1_in_f2 := encodeLengthDelimited(7, f7)
	f2.Write(encodeLengthDelimited(1, f1_in_f2))

	var f5_in_f2 bytes.Buffer
	f5_in_f2.Write(encodeLengthDelimited(2, []byte{}))
	f5_in_f2.Write(encodeLengthDelimited(3, []byte{}))

	var f5_5 bytes.Buffer
	f5_5.Write(encodeLengthDelimited(1, []byte{}))
	f5_5.Write(encodeInt(3, 0))
	f5_in_f2.Write(encodeLengthDelimited(5, f5_5.Bytes()))

	f2.Write(encodeLengthDelimited(5, f5_in_f2.Bytes()))
	buf.Write(encodeLengthDelimited(2, f2.Bytes()))

	return buf.Bytes()
}

// BuildCreateAlbumPayload constructs the payload for creating a shared album.
func BuildCreateAlbumPayload(albumName string, timestamp int64, mediaKeys []string) []byte {
	var buf bytes.Buffer

	// Field 1: albumName
	buf.Write(encodeString(1, albumName))

	// Field 2: timestamp
	buf.Write(encodeInt(2, timestamp))

	// Field 3: 1
	buf.Write(encodeInt(3, 1))

	// Field 4: repeated { 1: { 1: mediaKey } }
	for _, mk := range mediaKeys {
		item := encodeLengthDelimited(1, encodeString(1, mk))
		buf.Write(encodeLengthDelimited(4, item))
	}

	// Field 6: empty message
	buf.Write(encodeLengthDelimited(6, []byte{}))

	// Field 7: { 1: 3 }
	buf.Write(encodeLengthDelimited(7, encodeInt(1, 3)))

	// Field 8: { 3: "Pixel XL", 4: "Google", 5: 28 }
	var f8 bytes.Buffer
	f8.Write(encodeString(3, "Pixel XL"))
	f8.Write(encodeString(4, "Google"))
	f8.Write(encodeInt(5, 28))
	buf.Write(encodeLengthDelimited(8, f8.Bytes()))

	return buf.Bytes()
}

// BuildDeletePermanentlyPayload constructs the payload for permanent deletion.
func BuildDeletePermanentlyPayload(dedupKeys []string) []byte {
	var buf bytes.Buffer

	// Field 2: 2
	buf.Write(encodeInt(2, 2))

	// Field 3: repeated dedupKeys
	for _, dk := range dedupKeys {
		buf.Write(encodeString(3, dk))
	}

	// Field 4: 2
	buf.Write(encodeInt(4, 2))

	// Field 8: { 4: { 2: {}, 3: { 1: {} }, 4: {}, 5: { 1: {} } } }
	var f4 bytes.Buffer
	f4.Write(encodeLengthDelimited(2, []byte{}))
	f4.Write(encodeLengthDelimited(3, encodeLengthDelimited(1, []byte{})))
	f4.Write(encodeLengthDelimited(4, []byte{}))
	f4.Write(encodeLengthDelimited(5, encodeLengthDelimited(1, []byte{})))

	f8 := encodeLengthDelimited(4, f4.Bytes())
	buf.Write(encodeLengthDelimited(8, f8))

	// Field 9: empty string
	buf.Write(encodeString(9, ""))

	return buf.Bytes()
}

// BuildTrashPayload constructs the payload for moving items to trash.
func BuildTrashPayload(dedupKeys []string) []byte {
	var buf bytes.Buffer

	// Field 2: 1
	buf.Write(encodeInt(2, 1))

	// Field 3: repeated dedupKeys
	for _, dk := range dedupKeys {
		buf.Write(encodeString(3, dk))
	}

	// Field 4: 1
	buf.Write(encodeInt(4, 1))

	// Field 8: { 4: { 2: {}, 3: { 1: {} }, 4: {}, 5: { 1: {} } } }
	var f4 bytes.Buffer
	f4.Write(encodeLengthDelimited(2, []byte{}))
	f4.Write(encodeLengthDelimited(3, encodeLengthDelimited(1, []byte{})))
	f4.Write(encodeLengthDelimited(4, []byte{}))
	f4.Write(encodeLengthDelimited(5, encodeLengthDelimited(1, []byte{})))

	f8 := encodeLengthDelimited(4, f4.Bytes())
	buf.Write(encodeLengthDelimited(8, f8))

	// Field 9: { 1: 5, 2: { 1: 49029607, 2: "28" } }
	var f2 bytes.Buffer
	f2.Write(encodeInt(1, 49029607))
	f2.Write(encodeString(2, "28"))

	var f9 bytes.Buffer
	f9.Write(encodeInt(1, 5))
	f9.Write(encodeLengthDelimited(2, f2.Bytes()))
	buf.Write(encodeLengthDelimited(9, f9.Bytes()))

	return buf.Bytes()
}

// BuildFindByHashPayload constructs the payload for finding media by SHA-1 hash.
func BuildFindByHashPayload(sha1Bytes []byte) []byte {
	var buf bytes.Buffer

	// Field 1: { 1: { 1: sha1Bytes }, 2: {} }
	var f1 bytes.Buffer
	f1_1 := encodeLengthDelimited(1, sha1Bytes)
	f1.Write(encodeLengthDelimited(1, f1_1))
	f1.Write(encodeLengthDelimited(2, []byte{}))

	buf.Write(encodeLengthDelimited(1, f1.Bytes()))
	return buf.Bytes()
}

// BuildCreateShareLinkPayload constructs the payload for generating a public photos.app.goo.gl share link.
func BuildCreateShareLinkPayload(mediaKeys []string, timestampMs int64) []byte {
	var buf bytes.Buffer

	// Field 3
	buildItem7 := func(v1_1, v1_2, v2 int64) []byte {
		var f1 bytes.Buffer
		f1.Write(encodeInt(1, v1_1))
		f1.Write(encodeInt(2, v1_2))

		var item bytes.Buffer
		item.Write(encodeLengthDelimited(1, f1.Bytes()))
		item.Write(encodeInt(2, v2))
		return item.Bytes()
	}

	var f3 bytes.Buffer
	f3.Write(encodeInt(2, 1))
	f3.Write(encodeInt(5, 1))
	f3.Write(encodeLengthDelimited(7, buildItem7(2, 1, 1)))
	f3.Write(encodeLengthDelimited(7, buildItem7(2, 2, 1)))
	f3.Write(encodeLengthDelimited(7, buildItem7(1, 1, 0)))
	f3.Write(encodeLengthDelimited(7, buildItem7(1, 2, 0)))
	f3.Write(encodeLengthDelimited(7, buildItem7(3, 1, 1)))
	f3.Write(encodeInt(8, 0))
	buf.Write(encodeLengthDelimited(3, f3.Bytes()))

	// Field 4 (handles single or multiple media keys)
	var f4 bytes.Buffer
	f4.Write(encodeInt(1, 2))
	for _, mk := range mediaKeys {
		inner := encodeLengthDelimited(1, encodeString(1, mk))
		f4.Write(encodeLengthDelimited(3, inner))
	}
	f4.Write(encodeInt(7, 1))
	f4.Write(encodeInt(8, 1))
	f4.Write(encodeInt(9, 2))
	buf.Write(encodeLengthDelimited(4, f4.Bytes()))

	// Field 8 (timestamp in ms)
	buf.Write(encodeInt(8, timestampMs))

	// Field 9 ([3, 1, 2, 5])
	buf.Write(encodeInt(9, 3))
	buf.Write(encodeInt(9, 1))
	buf.Write(encodeInt(9, 2))
	buf.Write(encodeInt(9, 5))

	// Field 10 (Google Photos share read mask)
	maskHex := "0a2b12001a0022002a00320c0a0012001a0022002a003a003a004200520062006a0412001a007a020a0092010022020a004a005a0c0a0a0a0022002a0032004a0072220a200a1c0a0012060a020a001a001a1022060a020a001a002a060a020a001a0012008a01009201060a0012020a00a2010612040a001200b20100ba0100c20100"
	maskBytes, _ := hex.DecodeString(maskHex)
	buf.Write(encodeLengthDelimited(10, maskBytes))

	return buf.Bytes()
}
