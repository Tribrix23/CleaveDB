package main

import (
	"container/heap"
	"sort"
	"strings"
)

// MergeItem represents a single result item with a sort key.
type MergeItem struct {
	Value    string
	ShardIdx int
}

// MergeHeap implements heap.Interface for min-heap k-way merge.
type MergeHeap []MergeItem

func (h MergeHeap) Len() int            { return len(h) }
func (h MergeHeap) Less(i, j int) bool   { return h[i].Value < h[j].Value }
func (h MergeHeap) Swap(i, j int)        { h[i], h[j] = h[j], h[i] }
func (h *MergeHeap) Push(x interface{})  { *h = append(*h, x.(MergeItem)) }
func (h *MergeHeap) Pop() interface{} {
	old := *h
	n := len(old)
	item := old[n-1]
	*h = old[:n-1]
	return item
}

// KWayMerge merges sorted results from N shards using a min-heap.
// Each shard result is a comma-separated list of items (sorted within shard).
// Returns a single comma-separated merged result preserving sort order.
func KWayMerge(results []string) string {
	if len(results) == 0 {
		return ""
	}
	if len(results) == 1 {
		return results[0]
	}

	// Parse each shard's results into sorted slices
	shardItems := make([][]string, len(results))
	totalItems := 0
	for i, r := range results {
		if r == "" {
			shardItems[i] = nil
			continue
		}
		items := strings.Split(r, ", ")
		sort.Strings(items)
		shardItems[i] = items
		totalItems += len(items)
	}

	if totalItems == 0 {
		return ""
	}

	// Initialize the min-heap with the first element from each shard
	h := &MergeHeap{}
	heap.Init(h)
	shardPos := make([]int, len(results))

	for i, items := range shardItems {
		if len(items) > 0 {
			heap.Push(h, MergeItem{Value: items[0], ShardIdx: i})
			shardPos[i] = 1
		}
	}

	// Merge
	merged := make([]string, 0, totalItems)
	for h.Len() > 0 {
		item := heap.Pop(h).(MergeItem)
		merged = append(merged, item.Value)

		// Push next element from the same shard
		si := item.ShardIdx
		if shardPos[si] < len(shardItems[si]) {
			heap.Push(h, MergeItem{
				Value:    shardItems[si][shardPos[si]],
				ShardIdx: si,
			})
			shardPos[si]++
		}
	}

	return strings.Join(merged, ", ")
}
