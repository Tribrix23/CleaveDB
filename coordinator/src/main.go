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
	Port      int
	Shards    []string
	RaftNodes []string
	Timeout   time.Duration
}

type QueryRequest struct {
	Action   string    `json:"action,omitempty"`
	Query    string    `json:"query,omitempty"`
	Shards   []string  `json:"shards,omitempty"`
	Auth     *AuthInfo `json:"auth,omitempty"`
	Username string    `json:"username,omitempty"`
	Password string    `json:"password,omitempty"`
	SortKey  string    `json:"sort_key,omitempty"`
	ReqID    string    `json:"_req_id,omitempty"`
	RawQuery string    `json:"-"`
}

type AuthInfo struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type CatalogItem struct {
	Name          string            `json:"name"`
	StorageEngine string            `json:"storage_engine"`
	Status        string            `json:"status"`
	Size          string            `json:"size"`
	SizeBytes     int64             `json:"size_bytes"`
	Records       int64             `json:"records"`
	Schema        map[string]string `json:"schema"`
	LastActive    string            `json:"last_active"`
}

type CleaveQueryResult struct {
	Status        string                   `json:"status,omitempty"`
	Message       string                   `json:"message,omitempty"`
	Count         int                      `json:"count"`
	Type          string                   `json:"type,omitempty"`
	Bucket        string                   `json:"bucket,omitempty"`
	BucketStatus  string                   `json:"bucket_status,omitempty"`
	StorageEngine string                   `json:"storage_engine,omitempty"`
	Size          string                   `json:"size,omitempty"`
	SizeBytes     int64                    `json:"size_bytes,omitempty"`
	Records       int64                    `json:"records,omitempty"`
	Schema        map[string]string        `json:"schema,omitempty"`
	Sample        []map[string]interface{} `json:"sample,omitempty"`
	Catalogs      []CatalogItem            `json:"catalogs,omitempty"`
	Documents     []map[string]interface{} `json:"documents,omitempty"`
	Data          interface{}              `json:"data,omitempty"`
	Leader        string                   `json:"leader,omitempty"`
	Replicas      int                      `json:"replicas,omitempty"`
	Nodes         []string                 `json:"nodes,omitempty"`
	Shards        []string                 `json:"shards,omitempty"`
	Shard         string                   `json:"shard,omitempty"`
}

func extractBuckets(data interface{}) []string {
	var out []string
	if data == nil {
		return out
	}
	switch v := data.(type) {
	case []interface{}:
		for _, item := range v {
			if s, ok := item.(string); ok {
				out = append(out, s)
			}
		}
	case []string:
		out = append(out, v...)
	case string:
		if v != "" {
			out = append(out, v)
		}
	}
	return out
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

	// If auth is provided and this is not a direct login/register action, perform auth handshake with shard
	if req.Action != "login" && req.Action != "register" && req.Auth != nil && req.Auth.Username != "" {
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
	} else if req.Action == "login" || req.Action == "register" {
		payload, _ = json.Marshal(req)
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

	qText := strings.TrimSpace(req.Query)
	if qText == "" {
		qText = strings.TrimSpace(req.RawQuery)
	}
	qUpper := strings.ToUpper(qText)
	isCountBuckets := qUpper == "COUNT BUCKETS" || qUpper == "COUNT BUCKET"
	isShowBuckets := qUpper == "SHOW BUCKETS" || qUpper == "SHOW BUCKET"

	// If COUNT BUCKETS was requested, scatter SHOW BUCKETS so we get bucket names to deduplicate across shards
	scatterReq := req
	if isCountBuckets {
		scatterReq.Query = "SHOW BUCKETS"
		scatterReq.RawQuery = "SHOW BUCKETS"
		scatterReq.Action = "query"
	}

	resultsChan := make(chan ShardResponse, n)
	var wg sync.WaitGroup

	for i, addr := range shards {
		wg.Add(1)
		go func(idx int, target string) {
			defer wg.Done()
			res := queryShard(ctx, target, idx, scatterReq)
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

	// 1. Check for COUNT BUCKETS or SHOW BUCKETS merge
	if isCountBuckets || isShowBuckets {
		seenBuckets := make(map[string]bool)
		for _, r := range parsedResults {
			for _, b := range extractBuckets(r.Data) {
				if !strings.HasPrefix(b, "_") {
					parts := strings.Split(b, ".")
					cleanName := parts[len(parts)-1]
					if !strings.HasPrefix(cleanName, "_") {
						seenBuckets[cleanName] = true
					}
				}
			}
			for _, cat := range r.Catalogs {
				if !strings.HasPrefix(cat.Name, "_") {
					parts := strings.Split(cat.Name, ".")
					cleanName := parts[len(parts)-1]
					if !strings.HasPrefix(cleanName, "_") {
						seenBuckets[cleanName] = true
					}
				}
			}
		}

		if isCountBuckets {
			mergedResp := CleaveQueryResult{
				Status: "ok",
				Count:  len(seenBuckets),
				Type:   "buckets",
			}
			out, _ := json.Marshal([]CleaveQueryResult{mergedResp})
			return string(out)
		} else {
			bucketList := make([]string, 0, len(seenBuckets))
			for b := range seenBuckets {
				bucketList = append(bucketList, b)
			}
			sort.Strings(bucketList)
			mergedResp := CleaveQueryResult{
				Status: "ok",
				Data:   bucketList,
			}
			out, _ := json.Marshal([]CleaveQueryResult{mergedResp})
			return string(out)
		}
	}

	// If we successfully parsed CleaveDB structured results, merge them intelligently
	if len(parsedResults) > 0 {
		// 2. Check for Catalog results (DESCRIBE BUCKETS)
		hasCatalogs := false
		for _, r := range parsedResults {
			if len(r.Catalogs) > 0 {
				hasCatalogs = true
				break
			}
		}
		if hasCatalogs {
			mergedCatalogs := make(map[string]*CatalogItem)
			var catalogOrder []string

			for _, r := range parsedResults {
				for _, cat := range r.Catalogs {
					if strings.HasPrefix(cat.Name, "_") {
						continue
					}
					existing, found := mergedCatalogs[cat.Name]
					if !found {
						itemCopy := cat
						if itemCopy.Schema == nil {
							itemCopy.Schema = make(map[string]string)
						}
						mergedCatalogs[cat.Name] = &itemCopy
						catalogOrder = append(catalogOrder, cat.Name)
					} else {
						// Combine record counts and sizes across shards without duplicating bucket rows
						existing.Records += cat.Records
						existing.SizeBytes += cat.SizeBytes
						existing.Size = formatBytes(existing.SizeBytes)
						if cat.LastActive > existing.LastActive {
							existing.LastActive = cat.LastActive
						}
						for k, v := range cat.Schema {
							cur, exists := existing.Schema[k]
							if !exists || cur == "string" || cur == "unknown" || cur == "" {
								existing.Schema[k] = v
							}
						}
					}
				}
			}

			sort.Strings(catalogOrder)
			catalogsList := make([]CatalogItem, 0, len(catalogOrder))
			for _, name := range catalogOrder {
				catalogsList = append(catalogsList, *mergedCatalogs[name])
			}

			mergedResp := CleaveQueryResult{
				Status:   "ok",
				Count:    len(catalogsList),
				Catalogs: catalogsList,
			}
			out, _ := json.Marshal([]CleaveQueryResult{mergedResp})
			return string(out)
		}

		// 3. Check for single bucket describe (DESCRIBE BUCKET <name>)
		hasSingleBucket := false
		for _, r := range parsedResults {
			if r.Bucket != "" {
				hasSingleBucket = true
				break
			}
		}
		if hasSingleBucket {
			bucketName := ""
			storageEngine := "Document Vector"
			var totalRecords int64 = 0
			var totalSizeBytes int64 = 0
			mergedSchema := make(map[string]string)
			mergedSample := make([]map[string]interface{}, 0)
			seenSampleGids := make(map[string]bool)

			for _, r := range parsedResults {
				if r.Bucket != "" {
					bucketName = r.Bucket
					if r.StorageEngine != "" {
						storageEngine = r.StorageEngine
					}
					totalRecords += r.Records
					totalSizeBytes += r.SizeBytes
					for k, v := range r.Schema {
						cur, exists := mergedSchema[k]
						if !exists || cur == "string" || cur == "unknown" || cur == "" {
							mergedSchema[k] = v
						}
					}
					for _, s := range r.Sample {
						gid, _ := s["gid"].(string)
						if gid != "" {
							if seenSampleGids[gid] {
								continue
							}
							seenSampleGids[gid] = true
						}
						if len(mergedSample) < 10 {
							mergedSample = append(mergedSample, s)
						}
					}
				}
			}

			mergedResp := CleaveQueryResult{
				Status:        "ok",
				Bucket:        bucketName,
				StorageEngine: storageEngine,
				BucketStatus:  "Online",
				Records:       totalRecords,
				Size:          formatBytes(totalSizeBytes),
				SizeBytes:     totalSizeBytes,
				Schema:        mergedSchema,
				Sample:        mergedSample,
			}
			out, _ := json.Marshal([]CleaveQueryResult{mergedResp})
			return string(out)
		}

		// 4. Fallback for COUNT BUCKETS if shards returned raw count objects
		isBucketCount := false
		for _, r := range parsedResults {
			if r.Type == "buckets" {
				isBucketCount = true
				break
			}
		}
		if isBucketCount {
			maxCount := 0
			for _, r := range parsedResults {
				if r.Count > maxCount {
					maxCount = r.Count
				}
			}
			mergedResp := CleaveQueryResult{
				Status: "ok",
				Count:  maxCount,
				Type:   "buckets",
			}
			out, _ := json.Marshal([]CleaveQueryResult{mergedResp})
			return string(out)
		}

		// 5. Check for COUNT RAFT_NODES
		isRaftNodes := false
		for _, r := range parsedResults {
			if r.Leader != "" || len(r.Nodes) > 0 {
				isRaftNodes = true
				break
			}
		}
		if isRaftNodes {
			seenNodes := make(map[string]bool)
			nodesList := make([]string, 0)
			leader := ""
			for _, r := range parsedResults {
				if leader == "" && r.Leader != "" {
					leader = r.Leader
				}
				for _, n := range r.Nodes {
					if !seenNodes[n] {
						seenNodes[n] = true
						nodesList = append(nodesList, n)
					}
				}
			}
			if leader == "" && len(nodesList) > 0 {
				leader = nodesList[0]
			}
			replicas := len(nodesList) - 1
			if replicas < 0 {
				replicas = 0
			}
			mergedResp := CleaveQueryResult{
				Status:   "ok",
				Count:    len(nodesList),
				Leader:   leader,
				Replicas: replicas,
				Nodes:    nodesList,
			}
			out, _ := json.Marshal([]CleaveQueryResult{mergedResp})
			return string(out)
		}

		// 6. Merge documents
		mergedDocs := make([]map[string]interface{}, 0)
		seenGids := make(map[string]bool)
		totalCount := 0
		status := "ok"
		messages := make([]string, 0)

		for _, r := range parsedResults {
			if r.Status == "error" {
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

		if len(mergedDocs) == 0 && len(errors) > 0 {
			status = "error"
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
		if len(messages) > 0 && len(mergedDocs) == 0 {
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

func formatBytes(b int64) string {
	if b < 1024 {
		return fmt.Sprintf("%d B", b)
	}
	div, exp := int64(1024), 0
	for n := b / 1024; n >= 1024; n /= 1024 {
		div *= 1024
		exp++
	}
	units := []string{"KB", "MB", "GB", "TB"}
	return fmt.Sprintf("%.1f %s", float64(b)/float64(div), units[exp])
}

func handleClientConnection(conn net.Conn, cfg *CoordinatorConfig) {
	defer conn.Close()
	reader := bufio.NewReader(conn)
	var connAuth *AuthInfo

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
		} else {
			if req.Auth == nil && req.Username != "" {
				req.Auth = &AuthInfo{
					Username: req.Username,
					Password: req.Password,
				}
			}
		}

		// Inherit connection authenticated session if request did not specify auth explicitly
		if req.Auth == nil && connAuth != nil {
			req.Auth = connAuth
		}

		// Handle Ping / Status
		if req.Action == "ping" || strings.EqualFold(req.RawQuery, "PING") {
			statusResp, _ := json.Marshal(map[string]interface{}{
				"status":  "ok",
				"role":    "coordinator",
				"shards":  cfg.Shards,
				"version": "4.0.2",
			})
			conn.Write(append(statusResp, '\n'))
			continue
		}

		// Handle Login
		if req.Action == "login" {
			targetShards := cfg.Shards
			if len(req.Shards) > 0 {
				targetShards = req.Shards
			}
			ctx, cancel := context.WithTimeout(context.Background(), cfg.Timeout)
			result := ScatterGather(ctx, targetShards, req)
			cancel()

			// Check if login succeeded
			if strings.Contains(result, `"status":"ok"`) || strings.Contains(result, `"status": "ok"`) {
				if req.Auth != nil {
					connAuth = req.Auth
				} else if req.Username != "" {
					connAuth = &AuthInfo{Username: req.Username, Password: req.Password}
				}
			}

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
			continue
		}

		// Handle Register (broadcast to all shards)
		if req.Action == "register" {
			targetShards := cfg.Shards
			ctx, cancel := context.WithTimeout(context.Background(), cfg.Timeout)
			result := ScatterGather(ctx, targetShards, req)
			cancel()

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
			continue
		}

		// Handle COORDINATOR_NODES directly without scattering
		qUpper := strings.ToUpper(strings.TrimSpace(req.RawQuery))
		if qUpper == "" {
			qUpper = strings.ToUpper(strings.TrimSpace(req.Query))
		}
		if strings.Contains(qUpper, "COORDINATOR_NODES") {
			statusResp, _ := json.Marshal([]map[string]interface{}{{
				"status": "ok",
				"count":  len(cfg.Shards),
				"shards": cfg.Shards,
			}})
			conn.Write(append(statusResp, '\n'))
			continue
		}

		// Handle RAFT_NODES directly without scattering
		if strings.Contains(qUpper, "RAFT_NODES") {
			leader := "clv-node-01"
			if len(cfg.RaftNodes) > 0 {
				leader = cfg.RaftNodes[0]
			}
			replicas := len(cfg.RaftNodes) - 1
			if replicas < 0 {
				replicas = 0
			}
			statusResp, _ := json.Marshal([]map[string]interface{}{{
				"status":   "ok",
				"count":    len(cfg.RaftNodes),
				"leader":   leader,
				"replicas": replicas,
				"nodes":    cfg.RaftNodes,
			}})
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
	raftNodesFlag := flag.String("raft-nodes", "", "Comma-separated list of raft node addresses")
	timeoutSec := flag.Int("timeout", 5, "Scatter-gather timeout in seconds")
	flag.Parse()

	var shards []string
	for _, s := range strings.Split(*shardsFlag, ",") {
		s = strings.TrimSpace(s)
		if s != "" {
			shards = append(shards, s)
		}
	}

	var raftNodes []string
	if *raftNodesFlag != "" {
		for _, r := range strings.Split(*raftNodesFlag, ",") {
			r = strings.TrimSpace(r)
			if r != "" {
				raftNodes = append(raftNodes, r)
			}
		}
	}
	if len(raftNodes) == 0 {
		for _, s := range shards {
			host, _, err := net.SplitHostPort(s)
			if err == nil {
				raftNodes = append(raftNodes, net.JoinHostPort(host, "8311"))
			} else {
				raftNodes = append(raftNodes, s+":8311")
			}
		}
	}

	cfg := &CoordinatorConfig{
		Port:      *port,
		Shards:    shards,
		RaftNodes: raftNodes,
		Timeout:   time.Duration(*timeoutSec) * time.Second,
	}

	addr := fmt.Sprintf("0.0.0.0:%d", cfg.Port)
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("Failed to bind coordinator on %s: %v", addr, err)
	}
	defer listener.Close()

	fmt.Println("=========================================")
	fmt.Printf("   CleaveDB Go Coordinator v4.0.2\n")
	fmt.Printf("   Listening on TCP :%d\n", cfg.Port)
	fmt.Printf("   Configured Shards: %v\n", cfg.Shards)
	fmt.Printf("   Raft Nodes:        %v\n", cfg.RaftNodes)
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
