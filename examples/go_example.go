package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/masudranaxpert/photos-reverse-engine/core"
)

func main() {
	ctx := context.Background()

	// Load auth data from AUTH_DATA environment variable or pass directly
	authData := os.Getenv("AUTH_DATA")
	client, err := core.NewClient(authData)
	if err != nil {
		log.Fatalf("Failed to create client: %v", err)
	}

	// 1. Get active OAuth2 Bearer token
	token, err := client.GetToken(ctx)
	if err != nil {
		log.Fatalf("Failed to fetch token: %v", err)
	}
	fmt.Printf("[Go Engine] OAuth2 Token: %s...\n", token[:25])

	// 2. Demo: Check if an item exists by SHA-1 hash
	fakeHash := make([]byte, 20)
	existResult, err := client.FindMediaByHash(ctx, fakeHash)
	if err != nil {
		log.Printf("Hash lookup error (expected for zero hash): %v\n", err)
	} else {
		fmt.Printf("[Go Engine] Hash Lookup: Exists=%v\n", existResult.Exists)
	}
}
