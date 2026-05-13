"""Extended tests for memory_store.py covering previously-uncovered paths."""
import pytest
from memory_store import MemoryStore


class TestMemoryStoreReadWrite:
    """Test basic write and read operations of the memory store."""

    def test_write_and_read_back(self, tmp_path):
        """Test that we can write a summary and read it back via recall."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        # Save a test summary
        repo = "test-org/test-repo"
        summary = "Built authentication module with JWT tokens"
        row_id = store.save(repo=repo, summary=summary, mode="feature")
        
        # Verify it was saved
        assert row_id > 0
        
        # Recall should return our summary
        context = store.recall(repo=repo, recent_runs=5)
        assert "authentication module with JWT tokens" in context
        assert repo not in context  # repo name shouldn't be in the summary itself
        
        store.close()

    def test_write_multiple_and_recall_ordering(self, tmp_path):
        """Test that multiple entries are recalled in reverse chronological order."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Save multiple summaries
        store.save(repo=repo, summary="First feature: user login", mode="feature")
        store.save(repo=repo, summary="Second feature: password reset", mode="feature")
        store.save(repo=repo, summary="Third feature: email verification", mode="bugfix")
        
        # Recall should show them in reverse order (most recent first)
        context = store.recall(repo=repo, recent_runs=3)
        
        # Find positions of each string
        pos_first = context.find("First feature")
        pos_second = context.find("Second feature")
        pos_third = context.find("Third feature")
        
        # All should be present
        assert pos_first != -1
        assert pos_second != -1
        assert pos_third != -1
        
        # Third (most recent) should appear before first (oldest)
        # In recall output, they're reversed so oldest is first in the list
        assert pos_first < pos_third
        
        store.close()


class TestMemoryStoreSearch:
    """Test search functionality."""

    def test_search_finds_matching_entry(self, tmp_path):
        """Test that search finds entries matching keywords."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Save test entries with distinct keywords
        store.save(repo=repo, summary="Implemented authentication using JWT tokens")
        store.save(repo=repo, summary="Added database migration scripts")
        store.save(repo=repo, summary="Fixed authentication bug in login flow")
        
        # Search for "authentication" should find 2 entries
        results = store.search(repo=repo, keywords=["authentication"])
        
        assert "authentication" in results.lower()
        assert "JWT" in results or "jwt" in results.lower()
        assert "login flow" in results
        
        # Database entry should NOT appear in authentication search
        assert "database migration" not in results
        
        store.close()

    def test_search_returns_empty_for_no_match(self, tmp_path):
        """Test that search returns empty string when no entries match."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Save entries without "unicorn" keyword
        store.save(repo=repo, summary="Implemented user authentication")
        store.save(repo=repo, summary="Added database migrations")
        
        # Search for non-existent keyword
        results = store.search(repo=repo, keywords=["unicorn", "nonexistent"])
        
        # Should return empty string
        assert results == ""
        
        store.close()

    def test_search_with_multiple_keywords(self, tmp_path):
        """Test search with multiple keywords uses OR logic."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        store.save(repo=repo, summary="Implemented JWT authentication")
        store.save(repo=repo, summary="Added database schema migrations")
        store.save(repo=repo, summary="Fixed bug in payment processing")
        
        # Search with multiple keywords should find entries matching ANY keyword
        results = store.search(repo=repo, keywords=["authentication", "database"])
        
        # Should find both JWT and database entries
        assert "authentication" in results.lower() or "JWT" in results
        assert "database" in results.lower() or "schema" in results
        
        # Payment entry should not be there
        assert "payment" not in results.lower()
        
        store.close()


class TestMemoryStoreStats:
    """Test statistics and metadata operations."""

    def test_stats_returns_counts_by_tier(self, tmp_path):
        """Test that stats returns correct counts grouped by tier."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Save entries with different tiers
        store.save(repo=repo, summary="Run summary 1", tier="run")
        store.save(repo=repo, summary="Run summary 2", tier="run")
        store.save(repo=repo, summary="Monthly consolidation", tier="monthly")
        
        stats = store.stats(repo=repo)
        
        assert stats["run"] == 2
        assert stats["monthly"] == 1
        assert stats["total"] == 3
        
        store.close()

    def test_list_repos_returns_unique_repos(self, tmp_path):
        """Test that list_repos returns all unique repository slugs."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        # Save entries for multiple repos
        store.save(repo="org1/repo1", summary="Work on repo1")
        store.save(repo="org1/repo1", summary="More work on repo1")
        store.save(repo="org2/repo2", summary="Work on repo2")
        store.save(repo="org3/repo3", summary="Work on repo3")
        
        repos = store.list_repos()
        
        # Should have 3 unique repos
        assert len(repos) == 3
        assert "org1/repo1" in repos
        assert "org2/repo2" in repos
        assert "org3/repo3" in repos
        
        store.close()


class TestMemoryStoreDeprecationWarning:
    """Test that the datetime.utcnow() fix works correctly."""

    def test_write_no_utcnow_deprecation_warning(self, tmp_path, recwarn):
        """Test that save() does not trigger DeprecationWarning from datetime.utcnow()."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # This should not trigger any DeprecationWarning
        store.save(repo=repo, summary="Test summary to check for warnings")
        
        # Check that no DeprecationWarning was raised
        deprecation_warnings = [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
        
        # Filter for utcnow-related warnings specifically
        utcnow_warnings = [
            w for w in deprecation_warnings 
            if "utcnow" in str(w.message).lower()
        ]
        
        assert len(utcnow_warnings) == 0, (
            f"Expected no utcnow DeprecationWarnings, but got {len(utcnow_warnings)}: "
            f"{[str(w.message) for w in utcnow_warnings]}"
        )
        
        store.close()

    def test_multiple_writes_no_warnings(self, tmp_path, recwarn):
        """Test that multiple saves don't accumulate warnings."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Write multiple entries
        for i in range(5):
            store.save(repo=repo, summary=f"Test summary {i}")
        
        # Check no DeprecationWarnings
        deprecation_warnings = [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
        utcnow_warnings = [
            w for w in deprecation_warnings 
            if "utcnow" in str(w.message).lower()
        ]
        
        assert len(utcnow_warnings) == 0
        
        store.close()


class TestMemoryStoreConsolidation:
    """Test consolidation readiness checks."""

    def test_needs_consolidation_false_initially(self, tmp_path):
        """Test that a new repo doesn't need consolidation."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # No entries yet
        assert not store.needs_consolidation(repo=repo)
        
        # Add a few entries (less than threshold)
        for i in range(3):
            store.save(repo=repo, summary=f"Summary {i}")
        
        # Still shouldn't need consolidation (threshold is 10)
        assert not store.needs_consolidation(repo=repo)
        
        store.close()

    def test_needs_consolidation_true_after_threshold(self, tmp_path):
        """Test that needs_consolidation returns True after reaching threshold."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Add entries up to threshold (default is 10)
        for i in range(10):
            store.save(repo=repo, summary=f"Summary {i}")
        
        # Should need consolidation now
        assert store.needs_consolidation(repo=repo)
        
        store.close()

    def test_needs_consolidation_custom_threshold(self, tmp_path):
        """Test needs_consolidation with custom threshold."""
        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        
        repo = "test-org/test-repo"
        
        # Add 5 entries
        for i in range(5):
            store.save(repo=repo, summary=f"Summary {i}")
        
        # Should need consolidation with threshold=5
        assert store.needs_consolidation(repo=repo, threshold=5)
        
        # Should NOT need consolidation with threshold=10
        assert not store.needs_consolidation(repo=repo, threshold=10)
        
        store.close()
