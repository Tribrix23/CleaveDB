package main

/*
#include <stdlib.h>
*/
import "C"
import (
	"context"
	"fmt"
	"net"
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
			// Distributed Scatter: Send concurrent TCP requests to shard nodes
			// In a real cluster, each shardID maps to a different IP.
			// Here we route all shards to the local CleaveDB server port 8300
			conn, err := net.DialTimeout("tcp", "127.0.0.1:8300", 2*time.Second)
			if err != nil {
				// Fallback to direct string if server isn't up
				results <- fmt.Sprintf(`{"status": "error", "shard": %d, "error": "unreachable"}`, shardID)
				return
			}
			defer conn.Close()

			fmt.Fprintf(conn, "%s\n", qStr)

			var responseBuf []byte
			buf := make([]byte, 4096)
			conn.SetReadDeadline(time.Now().Add(3 * time.Second))
			for {
				nBytes, err := conn.Read(buf)
				if nBytes > 0 {
					responseBuf = append(responseBuf, buf[:nBytes]...)
				}
				if err != nil {
					break 
				}
			}

			select {
			case <-ctx.Done():
			case results <- string(responseBuf):
			}
		}(i)
	}

	collected := make([]string, 0, n)
	for i := 0; i < n; i++ {
		select {
		case <-ctx.Done():
			return C.CString(`{"status": "error", "message": "coordinator timeout"}`)
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
		}
	}()
}

func main() {}
