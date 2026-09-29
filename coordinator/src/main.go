package main

import "C"
import (
	"context"
	"fmt"
	"time"
	"unsafe"
)

//export ScatterGather
func ScatterGather(query *C.char, numShards C.int) *C.char {
	qStr := C.GoString(query)
	n := int(numShards)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	results := make(chan string, n)

	for i := 0; i < n; i++ {
		go func(shardID int) {
			// Mock shard query execution using the actual query string
			select {
			case <-ctx.Done():
			case results <- fmt.Sprintf("shard_%d:%s", shardID, qStr):
			}
		}(i)
	}

	collected := make([]string, 0, n)
	for i := 0; i < n; i++ {
		select {
		case <-ctx.Done():
			return C.CString("timeout")
		case res := <-results:
			collected = append(collected, res)
		}
	}

	merged := KWayMerge(collected)
	return C.CString(merged)
}

//export FreeCString
func FreeCString(s *C.char) {
	C.free(unsafe.Pointer(s))
}

//export StartBackgroundWorkers
func StartBackgroundWorkers() {
	go func() {
		for {
			time.Sleep(10 * time.Second)
			fmt.Println("[Go Coordinator] Background workers ran")
		}
	}()
}

func main() {}
