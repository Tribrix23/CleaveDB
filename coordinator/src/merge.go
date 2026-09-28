package main

import (
	"strings"
)

// KWayMerge merges sorted results from N shards.
// In a real scenario, this uses a Min/Max Heap on structured rows.
// For the prototype, we just concatenate.
func KWayMerge(results []string) string {
	return strings.Join(results, ", ")
}
