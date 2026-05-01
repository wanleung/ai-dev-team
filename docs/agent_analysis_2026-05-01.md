# AI Software House - Agent Roster & Skills Analysis

**Date:** 2026-05-01  
**Purpose:** Comprehensive review of all agents, their responsibilities, current skills, and improvement recommendations

---

## AGENT ROSTER

### PIPELINE COORDINATION (3 agents)

#### 1. **Product Manager (Alice)**
- **Role:** Translate raw requirements into PRD
- **Input:** User requirement (text, file, issue)
- **Output:** Structured PRD + GitHub Issue
- **Skills:**
  - Interviews stakeholder for clarity
  - Distills into SMART user stories
  - Defines acceptance criteria
  - Identifies project scope/risks
- **Current Strength:** Produces clear, actionable PRDs
- **Recommended Improvement:** ⭐ **CRITICAL** - Add checklist to ensure PRD includes:
  - User personas and their goals
  - Non-functional requirements (performance, scale, security)
  - Known constraints (budget, time, tech stack preferences)
  - Integration points with existing systems
  - Glossary of domain terms (for arch + engineers to reuse)

---

#### 2. **PM Reviewer (Grace)**
- **Role:** Review PRD for completeness; optionally revise before architecture
- **Input:** PRD + raw requirement
- **Output:** Verdict (APPROVED / NEEDS REVISION) + revised PRD
- **Skills:**
  - Validates acceptance criteria are testable
  - Checks scope is realistic
  - Ensures no ambiguities
- **Current Strength:** Catches incomplete requirements
- **Recommended Improvement:** Add structured review checklist:
  - [ ] All ACs are testable (specific inputs/outputs, not vague)
  - [ ] Scope aligns with time/resources
  - [ ] Technical assumptions documented (e.g., "requires 3rd-party auth API")
  - [ ] Risk mitigations listed
  - [ ] Glossary is populated

---

#### 3. **Architect (Bob)**
- **Role:** Design system architecture given PRD
- **Input:** PRD + optional clarification responses
- **Output:** System Design document with:
  - Technology stack + rationale
  - System components (responsibility + interfaces)
  - Data models (with SQL schema)
  - API endpoints (request/response specs)
  - Implementation modules (junior vs senior tier)
- **Skills:**
  - Chooses pragmatic tech stack
  - Breaks system into independently testable modules
  - Designs clear contracts (input/output types)
- **Current Strength:** Good separation of junior (self-contained) vs senior (orchestration) tiers
- **Recommended Improvement:** ⭐⭐ **CRITICAL FOR CHEAPER LLMS**
  1. **Add detailed pseudo-code for complex business logic:**
     - For each senior module, include a "Logic Flow" section with step-by-step pseudo-code
     - Example: "1. Validate user exists, 2. Check permissions, 3. Fetch data, 4. Transform, 5. Return"
     - This helps cheaper LLMs follow the exact sequence instead of improvising
  2. **Add validation rules matrix:**
     ```
     | Field | Type | Required | Constraints | Error Message |
     |-------|------|----------|-------------|---------------|
     | email | str  | yes      | valid email | "Invalid email" |
     ```
  3. **Add integration flow diagrams (text-based):**
     ```
     User Input → Validate → Check Auth → Call Service → Format Response
     ```
  4. **Add failure scenarios** for each endpoint:
     - "If user not found, return 404 with message 'User {id} not found'"
     - "If rate limit exceeded, return 429 with Retry-After header"

---

#### 4. **Arch Reviewer (Frank)**
- **Role:** Review system design for feasibility & correctness
- **Input:** Design + PRD
- **Output:** Verdict + optional revised design
- **Skills:**
  - Validates modules are independently testable
  - Checks for circular dependencies
  - Ensures tech stack matches PRD constraints
- **Current Strength:** Catches architectural flaws early
- **Recommended Improvement:**
  - Add checklist to validate:
    - [ ] All junior modules are truly self-contained (no cross-module imports)
    - [ ] All senior modules correctly import only junior modules
    - [ ] Error handling strategy is consistent across modules
    - [ ] All external API dependencies listed and documented
    - [ ] Performance assumptions (response times, throughput) are reasonable

---

### IMPLEMENTATION TEAM (2 tiers of engineers)

#### 5. **Junior Engineer (Jamie)**
- **Role:** Implement self-contained modules (models, schemas, utils, config)
- **Input:** Architecture spec + specific module assignment
- **Output:** Clean Python files (no cross-module dependencies)
- **Responsibilities:**
  - Data models (Pydantic, dataclasses)
  - Configuration loaders
  - Utility functions and validators
  - Constants and enums
- **Current Strength:** Focused scope reduces chance of errors
- **Recommended Improvement:**
  - Architect should provide **validation schema** for each junior module:
    ```
    # Example
    module: UserModel
    fields:
      - name: id
        type: int
        constraints: primary_key, auto-increment
      - name: email
        type: str
        constraints: unique, not_null, max_length=255, matches /^[^@]+@[^@]+\.[^@]+$/
      - name: created_at
        type: datetime
        constraints: default_to_now
    ```
  - Architect should include **example usage** for each utility:
    ```python
    # Usage example:
    from app.models import User
    user = User(email="test@example.com", name="John")
    assert user.email_is_valid()  # → True
    ```

---

#### 6. **Senior Engineer (Alex)**
- **Role:** Implement orchestration, services, routes (integrates junior code)
- **Input:** Architecture spec + junior code context + specific module assignment
- **Output:** Service layers, API routes, controllers
- **Responsibilities:**
  - Service layers and business logic
  - API routes and handlers
  - Authentication/authorization flows
  - Background tasks
- **Current Strength:** Clear requirement to reuse junior code; good separation of concerns
- **Recommended Improvement:** ⭐⭐ **CRITICAL FOR CHEAPER LLMS**
  1. **Architect provides detailed service specifications:**
     ```
     Service: UserService
     Methods:
       - get_user(user_id: int) -> User
         Precondition: user_id > 0
         Steps:
           1. Query database WHERE id = user_id
           2. If not found, raise UserNotFound(user_id)
           3. Return User object
         Error cases:
           - UserNotFound → 404 with message
           - DatabaseError → 500 with message
       - create_user(email: str, name: str) -> User
         Steps: [detailed list]
         Validation: 
           - email must be unique (check DB first)
           - email must be valid format
           - name must be 1-255 chars
     ```
  2. **Architect provides API endpoint specs with examples:**
     ```
     POST /api/users
     Request:
       { "email": "user@example.com", "name": "John Doe" }
     Response (201):
       { "id": 1, "email": "user@example.com", "name": "John Doe", "created_at": "2026-05-01T00:00:00Z" }
     Error Response (409):
       { "error": "email_already_exists" }
     ```
  3. **Step-by-step implementation checklist:**
     ```
     For POST /api/users endpoint:
     - [ ] Define route handler
     - [ ] Validate request body (use junior validators)
     - [ ] Call UserService.create_user()
     - [ ] Catch UserAlreadyExists and return 409
     - [ ] Return created user with 201 status
     ```

---

#### 7. **Junior Engineer (revision mode)**
- When PR feedback is received, architect should provide **what changed and why**
- Engineer then applies minimal diffs to fix issues

---

### QUALITY ASSURANCE (3 agents)

#### 8. **QA Planner (Henry)**
- **Role:** Design comprehensive test plan before writing any code
- **Input:** PRD + System Design + (optional) implemented code
- **Output:** Test Plan document with:
  - Acceptance criteria mapped to test scenarios
  - Test layers (unit, integration, API, E2E, performance, security)
  - Edge cases and negative tests
  - Test data requirements
  - Definition of Done
- **Skills:**
  - Maps each AC to concrete test cases
  - Identifies edge cases (nulls, oversized inputs, auth failures, etc.)
  - Prioritizes high-risk areas
- **Current Strength:** Structured output consumed by QA Engineer
- **Recommended Improvement:** ⭐⭐⭐ **CRITICAL FOR CHEAPER LLMS**
  1. **Add explicit test code templates** for QA Engineer to follow:
     ```python
     # Test Template for AC-01: User Registration
     def test_create_user_success():
         # Arrange
         email = "newuser@example.com"
         name = "John Doe"
         
         # Act
         response = client.post("/api/users", json={"email": email, "name": name})
         
         # Assert
         assert response.status_code == 201
         data = response.json()
         assert data["email"] == email
         assert data["name"] == name
         assert "id" in data
         assert "created_at" in data
     ```
  2. **Add mock/fixture definitions** for complex scenarios:
     ```python
     # Fixtures needed
     @pytest.fixture
     def authenticated_client():
         """Client with valid JWT token"""
         token = create_test_token(user_id=1)
         return Client(headers={"Authorization": f"Bearer {token}"})
     ```
  3. **Add boundary value matrix** for input validation tests:
     ```
     | Input | Type | Valid | Expected | Test ID |
     |-------|------|-------|----------|---------|
     | email | "" | No | 400 "email required" | test_email_empty |
     | email | "not-email" | No | 400 "invalid format" | test_email_invalid |
     | email | "a" * 300 | No | 400 "too long" | test_email_too_long |
     | email | "valid@example.com" | Yes | 201 | test_email_valid |
     ```
  4. **Add assertion details** so QA Engineer knows exact checks:
     ```
     When user updates their name:
     - Response status MUST be 200
     - Response body MUST contain updated_at timestamp (ISO 8601)
     - Database MUST reflect change
     - Audit log MUST record change with user_id and timestamp
     ```

---

#### 9. **QA Engineer (Edward)**
- **Role:** Implement all tests defined in Test Plan
- **Input:** Test Plan + implemented code
- **Output:** pytest test files + conftest + fixtures
- **Skills:**
  - Implements acceptance tests
  - Sets up test databases and fixtures
  - Runs tests and reports coverage
- **Current Strength:** Follows QA Planner specs
- **Recommended Improvement:**
  - QA Planner provides code templates (see above) so QA Engineer mostly copies/fills in values
  - Reduces cognitive load; faster implementation

---

#### 10. **Code Reviewer (Carol)**
- **Role:** Review code for correctness, security, design adherence
- **Input:** PR code + PRD + System Design
- **Output:** Review verdict + specific issues with fixes
- **Skills:**
  - Identifies logic errors and bugs
  - Checks for security vulnerabilities
  - Validates code matches design
- **Current Strength:** Structured review format
- **Recommended Improvement:** ⭐⭐ **CRITICAL - SUPERVISE ENGINEERS**
  1. **Add severity levels to all issues:**
     ```markdown
     ## CRITICAL (block merge)
     - Security vulnerability: SQL injection in query builder
     - Logic error: off-by-one in pagination
     
     ## MAJOR (requires fix before merge)
     - API response missing field required by acceptance criterion
     - Function not handling documented error case
     
     ## MINOR (nice to have)
     - Variable naming inconsistent with style guide
     - Comment could be clearer
     ```
  2. **Add specific "must fix" guidance:**
     ```
     ISSUE: UserService.get_user() does not validate user_id > 0
     REQUIRED FIX:
       Before: user = db.query(User).filter_by(id=user_id).first()
       After: 
         if user_id <= 0:
             raise ValueError("user_id must be > 0")
         user = db.query(User).filter_by(id=user_id).first()
     REASON: Architecture spec requires input validation; cheaper LLM might skip this
     ```
  3. **Add checklist before approval:**
     ```
     ## Pre-Approval Checklist for Code Review
     - [ ] All acceptance criteria addressed by code
     - [ ] All error cases documented in spec are handled
     - [ ] No SQL injection vulnerabilities
     - [ ] No hardcoded secrets
     - [ ] Error messages match API spec (e.g., "user not found" not "null pointer")
     - [ ] All inputs validated (types, ranges, formats)
     - [ ] All external API calls have timeouts and retry logic
     - [ ] Logger.info() for key operations (for debugging)
     ```
  4. **Add example of "good" for this domain:**
     ```
     PATTERN TO FOLLOW (for auth endpoints):
     1. Validate input exists and correct type
     2. Check rate limit
     3. Call service
     4. Catch specific exceptions (UserNotFound, InvalidPassword, etc.)
     5. Return appropriate HTTP status (401, 403, 404, etc.)
     6. Log security events (failed login, permission denied)
     ```

---

### DEPLOYMENT & DOCUMENTATION (4 agents)

#### 11. **Deployment Tester (Diana)**
- **Role:** Test deployment and generate smoke tests
- **Input:** Code + Dockerfile
- **Output:** docker-compose.test.yml + smoke test scripts
- **Responsibilities:**
  - Generates deployment test configs
  - Creates health check endpoint tests
- **Recommended Improvement:**
  - Architect should provide **deployment checklist**:
    - [ ] App starts without errors
    - [ ] All env vars configured
    - [ ] Database migrations run
    - [ ] Health check endpoint responds 200
    - [ ] Static assets served
    - [ ] API endpoints respond

---

#### 12. **QA Engineer (Test Execution)**
- **Role:** Run tests, report coverage and results
- **Input:** Test files + code
- **Output:** pytest report + coverage report
- **Responsibilities:**
  - Executes all tests
  - Reports pass/fail status and coverage %

---

#### 13. **Documentation Agent (DocGen)**
- **Role:** Write/update project documentation
- **Input:** System Design + implemented code
- **Output:** README + API docs + deployment guide

---

#### 14. **Memory Consolidator (Summarizer)**
- **Role:** Extract key decisions and tech debt for future reference
- **Input:** Full pipeline execution history
- **Output:** Compact memory entry
- **Responsibilities:**
  - Summarizes what was built
  - Records architectural decisions
  - Lists known tech debt
  - Notes feedback for next iteration

---

## SUMMARY TABLE

| Agent | Tier | Current Strength | Primary Recommendation |
|-------|------|------------------|------------------------|
| **Alice (PM)** | Requirements | Clear PRD output | ⭐ Add domain glossary + non-functional reqs checklist |
| **Grace (PM Reviewer)** | Requirements | Catches ambiguities | ⭐ Add structured review checklist |
| **Bob (Architect)** | Design | Good junior/senior separation | ⭐⭐⭐ Add pseudo-code, validation matrix, integration flows for each module |
| **Frank (Arch Reviewer)** | Design | Catches architectural flaws | ⭐ Add technical review checklist |
| **Jamie (Junior Eng)** | Implementation | Focused scope | ⭐ Architect provides validation schema + usage examples |
| **Alex (Senior Eng)** | Implementation | Reuses junior code well | ⭐⭐⭐ Architect provides detailed service specs + endpoint examples |
| **Carol (Code Reviewer)** | Quality | Structured reviews | ⭐⭐ Add severity levels, "must fix" guidance, pre-approval checklist |
| **Henry (QA Planner)** | Testing | Structured test plan | ⭐⭐⭐ Add test code templates, fixtures, boundary value matrix |
| **Edward (QA Eng)** | Testing | Implements tests | ⭐ QA Planner templates reduce cognitive load |
| **Diana (Deploy Tester)** | Deployment | Generates smoke tests | ⭐ Architect provides deployment checklist |
| **Summarizer** | Memory | Captures decisions | ✅ No changes needed |

---

## KEY INSIGHTS FOR CHEAPER LLMS

### Problem
Cheaper LLMs (gpt-4.1-mini, Ollama) struggle with:
1. **Ambiguous specs** — they guess instead of asking
2. **Missing edge cases** — they skip validation they don't see explicitly
3. **Integration points** — they may reimplement instead of reusing
4. **Supervision gaps** — they produce code that passes tests but violates business logic

### Solution: **Specification Depth**

**The more detail upstream agents provide, the cheaper the downstream LLM can be.**

#### Tier 1: Cheapest (Ollama, gpt-4-mini)
- Requires: Ultra-detailed specs (pseudo-code, validation matrices, error handler templates)
- Works best: Junior modules (self-contained models, utils)
- Needs: Code reviewer supervision (CRITICAL - cheaper LLMs produce more bugs)

#### Tier 2: Medium (gpt-4.1)
- Requires: Detailed specs (integration flows, service method signatures)
- Works best: Senior modules (services, routes integrating junior code)
- Needs: Code reviewer + acceptance test validation

#### Tier 3: Expensive (gpt-5, Claude-3)
- Requires: Moderate specs (design document + PRD)
- Works best: Complex orchestration, edge case handling
- Needs: Standard code review

### Implementation Strategy

1. **Use cheaper LLMs for junior modules** (always detailed, always isolated)
   - Architect: Provide validation schemas + error messages
   - Code Reviewer: Catch missing validators

2. **Use cheaper LLMs for well-specified services**
   - Architect: Provide pseudo-code, step-by-step logic
   - QA Planner: Provide test templates
   - Code Reviewer: Catch logic errors (must fix before merge)

3. **Use expensive LLMs only for**
   - Complex business orchestration
   - Novel technical challenges
   - Review feedback synthesis

---

## NEXT STEPS

1. **Update Architect role** to include:
   - Pseudo-code section for each senior module
   - Validation matrix for each data model
   - Integration flow diagrams

2. **Update QA Planner role** to include:
   - Test code templates (with arrange/act/assert structure)
   - Mock/fixture definitions
   - Boundary value matrix for inputs

3. **Update Code Reviewer role** to include:
   - Severity levels (CRITICAL/MAJOR/MINOR)
   - Must-fix guidance with before/after code
   - Pre-approval checklist

4. **Test with cheaper LLM** (e.g., Ollama + gpt-4-mini) on next feature:
   - Architect: Use new detailed spec format
   - Engineer (junior): Use Ollama
   - Code Reviewer: Strict supervision (expect more bugs to catch)
   - Measure: Time to fix + quality of result

