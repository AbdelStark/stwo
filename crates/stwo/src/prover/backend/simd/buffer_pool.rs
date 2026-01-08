//! Thread-local buffer pool for reducing allocation overhead in hot paths.
//!
//! This module provides a simple buffer pooling mechanism for frequently allocated
//! SIMD vectors. The pool caches released buffers by size class and reuses them
//! for subsequent allocations, reducing the cost of heap allocation in performance-
//! critical paths like FRI folding and quotient computation.
//!
//! # Usage
//!
//! ```ignore
//! // Get a buffer from the pool (or allocate new if none available)
//! let mut buffer = BufferPool::take_base_field(size);
//!
//! // Use the buffer...
//! // Buffer is automatically returned to pool on drop
//! ```

use std::cell::RefCell;
use std::collections::HashMap;

use super::m31::PackedBaseField;

/// Maximum number of buffers to cache per size class.
const MAX_CACHED_BUFFERS_PER_SIZE: usize = 4;

/// Maximum buffer size to cache (in packed elements). Buffers larger than this
/// are not cached to avoid excessive memory usage.
/// 2^20 packed elements = 2^24 field elements = 64MB
const MAX_CACHEABLE_SIZE: usize = 1 << 20;

// Thread-local storage for base field buffers, keyed by packed size.
thread_local! {
    static BASE_FIELD_POOL: RefCell<HashMap<usize, Vec<Vec<PackedBaseField>>>> =
        RefCell::new(HashMap::new());
}

/// A pooled buffer that returns itself to the pool on drop.
///
/// This wrapper provides automatic buffer recycling. When dropped, the buffer
/// is returned to the thread-local pool for reuse by future allocations.
pub struct PooledBaseFieldBuffer {
    /// The underlying buffer. Option is used to allow taking ownership on drop.
    buffer: Option<Vec<PackedBaseField>>,
    /// The size class (packed length) for pool indexing.
    size: usize,
}

impl PooledBaseFieldBuffer {
    /// Creates a new pooled buffer with the given capacity.
    fn new(capacity: usize) -> Self {
        Self {
            buffer: Some(Vec::with_capacity(capacity)),
            size: capacity,
        }
    }

    /// Creates a pooled buffer wrapping an existing vector.
    const fn from_vec(buffer: Vec<PackedBaseField>) -> Self {
        let size = buffer.capacity();
        Self {
            buffer: Some(buffer),
            size,
        }
    }

    /// Returns a mutable reference to the underlying buffer.
    #[inline]
    #[allow(clippy::missing_const_for_fn)] // unwrap() is not const-stable
    pub fn get_mut(&mut self) -> &mut Vec<PackedBaseField> {
        self.buffer.as_mut().unwrap()
    }

    /// Returns a reference to the underlying buffer.
    #[inline]
    #[allow(clippy::missing_const_for_fn)] // unwrap() is not const-stable
    pub fn get(&self) -> &Vec<PackedBaseField> {
        self.buffer.as_ref().unwrap()
    }

    /// Consumes the pooled buffer and returns the underlying vector.
    /// The buffer will NOT be returned to the pool.
    #[inline]
    #[allow(clippy::missing_const_for_fn)] // take()/unwrap() are not const-stable
    pub fn into_vec(mut self) -> Vec<PackedBaseField> {
        self.buffer.take().unwrap()
    }
}

impl Drop for PooledBaseFieldBuffer {
    fn drop(&mut self) {
        if let Some(mut buffer) = self.buffer.take() {
            // Only cache if the buffer is within our size limits
            if self.size <= MAX_CACHEABLE_SIZE {
                buffer.clear();
                BASE_FIELD_POOL.with(|pool| {
                    let mut pool = pool.borrow_mut();
                    let entry = pool.entry(self.size).or_default();
                    if entry.len() < MAX_CACHED_BUFFERS_PER_SIZE {
                        entry.push(buffer);
                    }
                    // If cache is full, just drop the buffer
                });
            }
            // Buffers exceeding MAX_CACHEABLE_SIZE are dropped normally
        }
    }
}

/// Buffer pool providing thread-local caching of SIMD vector allocations.
///
/// This is the main interface for the buffer pooling system. It provides
/// methods to acquire buffers that are either retrieved from the cache
/// or freshly allocated.
pub struct BufferPool;

impl BufferPool {
    /// Acquires a base field buffer of at least the specified packed size.
    ///
    /// If a cached buffer of the exact size is available, it is returned.
    /// Otherwise, a new buffer is allocated.
    ///
    /// The returned buffer is wrapped in `PooledBaseFieldBuffer` which
    /// automatically returns it to the pool when dropped.
    ///
    /// # Arguments
    ///
    /// * `packed_size` - The required capacity in packed elements (PackedBaseField units)
    #[inline]
    pub fn take_base_field(packed_size: usize) -> PooledBaseFieldBuffer {
        // Try to get from pool first
        let cached = BASE_FIELD_POOL.with(|pool| {
            let mut pool = pool.borrow_mut();
            if let Some(buffers) = pool.get_mut(&packed_size) {
                buffers.pop()
            } else {
                None
            }
        });

        match cached {
            Some(buffer) => PooledBaseFieldBuffer::from_vec(buffer),
            None => PooledBaseFieldBuffer::new(packed_size),
        }
    }

    /// Clears all cached buffers from the pool.
    ///
    /// This can be called to release memory when the prover is done
    /// with a batch of operations.
    pub fn clear() {
        BASE_FIELD_POOL.with(|pool| {
            pool.borrow_mut().clear();
        });
    }

    /// Returns statistics about the current pool state.
    ///
    /// Returns a vector of (size_class, buffer_count) pairs.
    #[cfg(test)]
    pub fn stats() -> Vec<(usize, usize)> {
        BASE_FIELD_POOL.with(|pool| {
            pool.borrow()
                .iter()
                .map(|(&size, buffers)| (size, buffers.len()))
                .collect()
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_buffer_pool_basic() {
        // Clear any existing state
        BufferPool::clear();

        // Take a buffer
        let buffer = BufferPool::take_base_field(64);
        assert_eq!(buffer.get().capacity(), 64);

        // Drop the buffer - should return to pool
        drop(buffer);

        // Stats should show one cached buffer
        let stats = BufferPool::stats();
        assert!(stats.iter().any(|&(size, count)| size == 64 && count == 1));

        // Take another buffer of same size - should reuse
        let buffer2 = BufferPool::take_base_field(64);
        assert_eq!(buffer2.get().capacity(), 64);

        // Pool should now be empty for this size
        let stats = BufferPool::stats();
        assert!(stats.iter().all(|&(size, count)| size != 64 || count == 0));
    }

    #[test]
    fn test_buffer_pool_max_cached() {
        BufferPool::clear();

        // Create MAX_CACHED_BUFFERS_PER_SIZE + 2 fresh buffers (not from pool)
        // and keep them alive before dropping
        let buffers: Vec<_> = (0..MAX_CACHED_BUFFERS_PER_SIZE + 2)
            .map(|_| {
                // Use into_vec to bypass pool for allocation
                let mut v = Vec::with_capacity(128);
                unsafe { v.set_len(0) };
                PooledBaseFieldBuffer::from_vec(v)
            })
            .collect();

        // Drop all buffers - they should try to return to pool
        drop(buffers);

        // Should only have MAX_CACHED_BUFFERS_PER_SIZE cached
        let stats = BufferPool::stats();
        let count = stats
            .iter()
            .find(|&&(size, _)| size == 128)
            .map(|&(_, c)| c)
            .unwrap_or(0);
        assert_eq!(count, MAX_CACHED_BUFFERS_PER_SIZE);
    }

    #[test]
    fn test_into_vec_does_not_return_to_pool() {
        BufferPool::clear();

        let buffer = BufferPool::take_base_field(256);
        let _vec = buffer.into_vec();

        // Should not have any cached buffers since we took ownership
        let stats = BufferPool::stats();
        assert!(stats.iter().all(|&(size, count)| size != 256 || count == 0));
    }
}
