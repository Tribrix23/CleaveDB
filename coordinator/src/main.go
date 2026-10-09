package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

type ShardResponse struct {
	ShardID int
	Address string
	Data    string
	Err     error
}

type CoordinatorConfig struct {
	Port    int
	Shards  []string
	Timeout time.Duration
}

type QueryRequest struct {
	Action   string          `json:"action,omitempty"`
	Query    string          `json:"query,omitempty"`
	Shards   []string        `json:"shards,omitempty"`
	Auth     *AuthInfo       `json:"auth,omitempty"`
	SortKey  string          `json:"sort_key,omitempty"`
	ReqID    string          `json:"_req_id,omitempty"`
	RawQuery string          `json:"-"`
}

type AuthInfo struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type CleaveQueryResult struct {
	Status    string                   `json:"status,omitempty"`
	Message   string                   `json:"message,omitempty"`
	Count     int                      `json:"count,omitempty"`
	Documents []map[string]interface{} `json:"documents,omitempty"`
	Data      interface{}              `json:"data,omitempty"`
	Shard     string                   `json:"shard,omitempty"`
}

func queryShard(ctx context.Context, shardAddr string, shardID int, req QueryRequest) ShardResponse {
	d := net.Dialer{Timeout: 3 * time.Second}
	conn, err := d.DialContext(ctx, "tcp", shardAddr)
	if err != nil {
		return ShardResponse{
			ShardID: shardID,
			Address: shardAddr,
			Err:     fmt.Errorf("dial failed: %w", err),
		}
	}
	defer conn.Close()

	reader := bufio.NewReader(conn)

	// If auth is provided, perform auth handshake with shard
	if req.Auth != nil && req.Auth.Username != "" {
		loginMsg, _ := json.Marshal(map[string]string{
			"action":   "login",
			"username": req.Auth.Username,
			"password": req.Auth.Password,
		})
		_, err = conn.Write(append(loginMsg, '\n'))
		if err != nil {
			return ShardResponse{ShardID: shardID, Address: shardAddr, Err: fmt.Errorf("auth send failed: %w", err)}
		}
		// Read auth response
		_, err = reader.ReadString('\n')
		if err != nil {
			return ShardResponse{ShardID: shardID, Address: shardAddr, Err: fmt.Errorf("auth read failed: %w", err)}
		}
	}

	// Prepare query payload
	var payload []byte
	queryText := req.Query
	if queryText == "" {
		queryText = req.RawQuery
	}

	if strings.HasPrefix(strings.TrimSpace(queryText), "{") {
		payload = []byte(queryText)
	} else {
		msg := map[string]interface{}{
			"action": "query",
			"query":  queryText,
		}
		if req.ReqID != "" {
			msg["_req_id"] = req.ReqID
		}
		payload, _ = json.Marshal(msg)
	}

	// Write query
	if _, err := conn.Write(append(payload, '\n')); err != nil {
		return ShardResponse{ShardID: shardID, Address: shardAddr, Err: fmt.Errorf("write query failed: %w", err)}
	}

	// Read response with deadline
	if deadline, ok := ctx.Deadline(); ok {
		conn.SetReadDeadline(deadline)
	}

	line, err := reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return ShardResponse{ShardID: shardID, Address: shardAddr, Err: fmt.Errorf("read response failed: %w", err)}
	}

	return ShardResponse{
		ShardID: shardID,
		Address: shardAddr,
		Data:    strings.TrimSpace(line),
		Err:     nil,
	}
}

func ScatterGather(ctx context.Context, shards []string, req QueryRequest) string {
	n := len(shards)
	if n == 0 {
		resp, _ := json.Marshal([]map[string]string{{"status": "error", "message": "no shards configured"}})
		return string(resp)
	}

	resultsChan := make(chan ShardResponse, n)
	var wg sync.WaitGroup

	for i, addr := range shards {
		wg.Add(1)
		go func(idx int, target string) {
			defer wg.Done()
			res := queryShard(ctx, target, idx, req)
			resultsChan <- res
		}(i, addr)
	}

	wg.Wait()
	close(resultsChan)

	rawResponses := make([]string, 0, n)
	parsedResults := make([]CleaveQueryResult, 0, n)
	errors := make([]string, 0)

	for res := range resultsChan {
		if res.Err != nil {
			errors = append(errors, fmt.Sprintf("shard %s error: %v", res.Address, res.Err))
			continue
		}
		if res.Data == "" {
			continue
		}

		rawResponses = append(rawResponses, res.Data)

		// Try parsing as CleaveDB standard result list: [ { "status": "ok", "documents": [...] } ]
		var items []CleaveQueryResult
		if err := json.Unmarshal([]byte(res.Data), &items); err == nil && len(items) > 0 {
			for _, item := range items {
				item.Shard = res.Address
				parsedResults = append(parsedResults, item)
			}
		} else {
			// Try single object
			var single CleaveQueryResult
			if err := json.Unmarshal([]byte(res.Data), &single); err == nil {
				single.Shard = res.Address
				parsedResults = append(parsedResults, single)
			}
		}
	}

	// If we successfully parsed CleaveDB structured results, merge them intelligently
	if len(parsedResults) > 0 {
		mergedDocs := make([]map[string]interface{}, 0)
		seenGids := make(map[string]bool)
		totalCount := 0
		status := "ok"
		messages := make([]string, 0)

		for _, r := range parsedResults {
			if r.Status == "error" {
				status = "error"
				if r.Message != "" {
					messages = append(messages, r.Message)
				}
			}
			for _, doc := range r.Documents {
				gid, _ := doc["gid"].(string)
				if gid != "" {
					if seenGids[gid] {
						continue // Deduplicate identical documents across replicas/shards
					}
					seenGids[gid] = true
				}
				mergedDocs = append(mergedDocs, doc)
			}
			totalCount += r.Count
		}

		// Sort merged documents if sort key is provided
		if req.SortKey != "" {
			sort.Slice(mergedDocs, func(i, j int) bool {
				vi := fmt.Sprintf("%v", mergedDocs[i][req.SortKey])
				vj := fmt.Sprintf("%v", mergedDocs[j][req.SortKey])
				return vi < vj
			})
		}

		if len(mergedDocs) > 0 && totalCount == 0 {
			totalCount = len(mergedDocs)
		}

		mergedItem := CleaveQueryResult{
			Status:    status,
			Count:     totalCount,
			Documents: mergedDocs,
		}
		if len(messages) > 0 {
			mergedItem.Message = strings.Join(messages, "; ")
		}

		out, _ := json.Marshal([]CleaveQueryResult{mergedItem})
		return string(out)
	}

	// Fallback to K-Way Merge for non-JSON or raw list strings
	if len(rawResponses) > 0 {
		merged := KWayMerge(rawResponses)
		if merged != "" {
			return merged
		}
		return rawResponses[0]
	}

	errResp, _ := json.Marshal([]map[string]string{
		{"status": "error", "message": strings.Join(errors, ", ")},
	})
	return string(errResp)
}

func handleClientConnection(conn net.Conn, cfg *CoordinatorConfig) {
	defer conn.Close()
	reader := bufio.NewReader(conn)

	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			return
		}

		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		var req QueryRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			req.RawQuery = line
		}

		// Handle Ping / Status
		if req.Action == "ping" || strings.EqualFold(req.RawQuery, "PING") {
			statusResp, _ := json.Marshal(map[string]interface{}{
				"status":  "ok",
				"role":    "coordinator",
				"shards":  cfg.Shards,
				"version": "4.0.0",
			})
			conn.Write(append(statusResp, '\n'))
			continue
		}

		// Determine target shards
		targetShards := cfg.Shards
		if len(req.Shards) > 0 {
			targetShards = req.Shards
		}

		// Execute ScatterGather with timeout
		ctx, cancel := context.WithTimeout(context.Background(), cfg.Timeout)
		result := ScatterGather(ctx, targetShards, req)
		cancel()

		// Wrap response if _req_id was provided
		if req.ReqID != "" {
			var rawVal interface{}
			if err := json.Unmarshal([]byte(result), &rawVal); err == nil {
				wrapped, _ := json.Marshal(map[string]interface{}{
					"_req_id": req.ReqID,
					"payload": rawVal,
				})
				result = string(wrapped)
			}
		}

		conn.Write([]byte(result + "\n"))
	}
}

func main() {
	port := flag.Int("port", 8305, "Port to listen on for cluster queries")
	shardsFlag := flag.String("shards", "127.0.0.1:8300", "Comma-separated list of shard addresses")
	timeoutSec := flag.Int("timeout", 5, "Scatter-gather timeout in seconds")
	flag.Parse()

	var shards []string
	for _, s := range strings.Split(*shardsFlag, ",") {
		s = strings.TrimSpace(s)
		if s != "" {
			shards = append(shards, s)
		}
	}

	cfg := &CoordinatorConfig{
		Port:    *port,
		Shards:  shards,
		Timeout: time.Duration(*timeoutSec) * time.Second,
	}

	addr := fmt.Sprintf("0.0.0.0:%d", cfg.Port)
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("Failed to bind coordinator on %s: %v", addr, err)
	}
	defer listener.Close()

	fmt.Println("=========================================")
	fmt.Printf("   CleaveDB Go Coordinator v4.0.0\n")
	fmt.Printf("   Listening on TCP :%d\n", cfg.Port)
	fmt.Printf("   Configured Shards: %v\n", cfg.Shards)
	fmt.Printf("   Scatter Timeout:   %v\n", cfg.Timeout)
	fmt.Println("=========================================")

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		fmt.Println("\n[Coordinator] Shutting down...")
		listener.Close()
		os.Exit(0)
	}()

	for {
		conn, err := listener.Accept()
		if err != nil {
			break
		}
		go handleClientConnection(conn, cfg)
	}
}
