# PR-006: Implement product inventory caching

## Description
Add a caching layer for product inventory lookups to reduce database load and improve response times for product pages. The cache should be invalidated when inventory is updated.

## Requirements
- Cache inventory counts in Redis with 5-minute TTL
- Invalidate cache when inventory changes via order placement or admin updates
- Serve cached inventory from product detail endpoint
- Fallback to database on cache miss

## Acceptance Criteria
- [ ] Product inventory is cached after first read
- [ ] Cache TTL is set to 5 minutes
- [ ] Cache is invalidated when orders reduce inventory
- [ ] Cache is invalidated when admin updates stock
- [ ] Cache miss falls back to database query
- [ ] System remains consistent under concurrent access