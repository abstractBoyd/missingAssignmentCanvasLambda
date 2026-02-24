import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

API_ONE = "/api/v1"
COURSES_URL = API_ONE + "/courses"
DASHBOARD_CARDS_URL = API_ONE + "/dashboard/dashboard_cards"
#GRADES_URL = API_ONE + "/courses"
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "").rstrip("/")
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")
OBSERVED_USER_ID = os.environ.get("OBSERVED_USER_ID")  # optional: set to pick a specific observee
CUTOFF_DATE = os.environ.get("CUTOFF_DATE", "")
# Lock CORS down to your site; use "*" only for quick testing.
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Missing Assignments</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 20px; }
    h2 { margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }
    h3 { margin-top: 18px; }
    ul { margin-top: 8px; }
    li { margin: 4px 0; }
    .muted { color: #666; font-size: 0.9em; }
    .error { color: #b00020; white-space: pre-wrap; }
    .spinner { display: inline-block; width: 10px; height: 10px; border: 2px solid #bbb; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 6px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .course-box { padding: 10px 12px; border: 1px solid #eee; border-radius: 10px; margin: 10px 0; }
  </style>
</head>
<body>
  <h1>Missing Assignments</h1>
  <div id="status" class="muted"></div>
  <div id="out"></div>

<script>
  // ✅ Set this to your Lambda Function URL (no trailing slash)
  const LAMBDA_URL = window.location.origin + window.location.pathname;

  const statusEl = document.getElementById("status");
  const outEl = document.getElementById("out");

  function setStatus(msg) {
    statusEl.innerHTML = msg ? `<span class="spinner"></span>${msg}` : "";
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, ch => ({
      "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
    }[ch]));
  }

  async function callApi(params) {
    const u = new URL(LAMBDA_URL);
    Object.entries(params).forEach(([k,v]) => {
      if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, v);
    });

    const res = await fetch(u.toString(), { headers: { "Accept": "application/json" }});
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}\n${txt}`);
    }
    return res.json();
  }

  function renderStudentShell(studentName) {
    const id = `student_${studentName.replace(/\W+/g, "_")}`;
    const div = document.createElement("div");
    div.id = id;
    div.innerHTML = `<h2>${escapeHtml(studentName)}</h2><div class="muted">Loading courses…</div>`;
    outEl.appendChild(div);
    return div;
  }

  function renderCourseShell(parentDiv, courseName) {
    const box = document.createElement("div");
    box.className = "course-box";
    box.innerHTML = `<h3>${escapeHtml(courseName)}</h3><div class="muted">Loading assignments…</div>`;
    parentDiv.appendChild(box);
    return box;
  }

  function renderAssignments(courseDiv, assignments) {
    if (!assignments || assignments.length === 0) {
      courseDiv.querySelector(".muted").textContent = "No matching assignments.";
      return;
    }

    const items = assignments.map(a => {
      const name = escapeHtml(a.name || "Untitled");
      const url = escapeHtml(a.html_url || a.url || "#");
      const due = escapeHtml(a.due_at || a.due || "");
      const pts = escapeHtml(a.points_possible ?? "");
      const scr = escapeHtml(a.score ?? "");
      return `<li><a href="${url}" target="_blank" rel="noopener">${name}</a>
              <span class="muted"> — Due: ${due} — Points: ${scr}/${pts}</span>
              </li>`;
    }).join("");

    courseDiv.innerHTML = `<h3>${courseDiv.querySelector("h3").innerText}</h3><ul>${items}</ul>`;
  }

  async function getScore(studentId, courseId, assignmentId) {
    const u = new URL(window.location.origin + window.location.pathname);
    u.searchParams.set("data_type", "score");
    u.searchParams.set("observed_user_id", studentId);
    u.searchParams.set("course_id", courseId);
    u.searchParams.set("assignment_id", assignmentId);

    const res = await fetch(u.toString(), { headers: { "Accept": "application/json" }});
    if (!res.ok) return null;

    const data = await res.json();
    return data ?? null;
}

  function renderError(container, err) {
    container.innerHTML = `<div class="error">${escapeHtml(err.stack || err.message || String(err))}</div>`;
  }

  async function loadAll() {
    outEl.innerHTML = "";
    setStatus("Loading students…");

    // 1) get observees (students)
    const observees = await callApi({ data_type: "observees" });

    if (!observees || observees.length === 0) {
      setStatus("");
      outEl.innerHTML = `<div class="muted">No observees found.</div>`;
      return;
    }

    setStatus(`Found ${observees.length} students. Loading courses…`);

    // 2) For each student: load courses + then assignments per course, all async
    await Promise.all(observees.map(async (stu) => {
      const studentDiv = renderStudentShell(stu.name || `Student ${stu.id}`);

      try {
        const courses = await callApi({
          data_type: "courses",
          observed_user_id: stu.id
        });

        studentDiv.innerHTML = `<h2>${escapeHtml(stu.name || `Student ${stu.id}`)}</h2>`;

        if (!courses || courses.length === 0) {
          const m = document.createElement("div");
          m.className = "muted";
          m.textContent = "No courses found.";
          studentDiv.appendChild(m);
          return;
        }

        // Create course boxes immediately (so UI feels responsive)
        const courseBoxes = courses.map(c => ({
          course: c,
          box: renderCourseShell(studentDiv, c.name || `Course ${c.id}`)
        }));

        // 3) Load assignments for each course concurrently
        await Promise.all(courseBoxes.map(async ({course, box}) => {
          try {
            const assignments = await callApi({
              data_type: "assignments",
              observed_user_id: stu.id,
              course_id: course.id
            });

            // 🔥 Fetch scores in parallel
            const filtered = await Promise.all(assignments.map(async (a) => {
              const score = await getScore(stu.id, course.id, a.id);
              a.score = score
              if (score == null) {
                // no score → keep it
                return a;
              }
              if (score == 'grading') {
                // being graded, filter out
                return null;
              }

              const halfPoints = (a.points_possible || 0) / 2;

              if (score >= halfPoints) {
                return null; // filter out
              }

              return a;
            }));

            // remove nulls
            const finalAssignments = filtered.filter(Boolean);

            renderAssignments(box, finalAssignments);


          } catch (e) {
            renderError(box, e);
          }
        }));

      } catch (e) {
        renderError(studentDiv, e);
      }
    }));

    setStatus("");
  }

  loadAll().catch(e => {
    setStatus("");
    outEl.innerHTML = `<div class="error">${escapeHtml(e.stack || e.message || String(e))}</div>`;
  });
</script>
</body>
</html>
"""

def _iso_to_dt(s: str | None):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def _canvas_get(path: str, params: dict | None = None):
    """
    GET a Canvas endpoint and follow pagination via Link headers.
    Uses urllib (built-in) so no external dependencies needed for Lambda.
    Returns a list.
    """
    if not CANVAS_BASE_URL or not CANVAS_TOKEN:
        raise ValueError("Missing CANVAS_BASE_URL or CANVAS_TOKEN environment variables.")

    # Build initial URL
    url = f"{CANVAS_BASE_URL}{path}"
    if params:
        # support list params like course_ids[] by allowing values to be lists
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    items = []
    while url:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {CANVAS_TOKEN}")
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)

            # Canvas usually returns arrays for these endpoints
            if isinstance(data, list):
                items.extend(data)
            else:
                # If Canvas returns an object, still return it (wrapped)
                items.append(data)

            # Parse Link header for pagination
            link = resp.headers.get("Link")
            next_url = None
            if link:
                # format: <url>; rel="next", <url>; rel="current", ...
                parts = [p.strip() for p in link.split(",")]
                for p in parts:
                    if 'rel="next"' in p:
                        start = p.find("<") + 1
                        end = p.find(">")
                        next_url = p[start:end] if start > 0 and end > start else None
                        break
            url = next_url

    return items

def get_courses(observed_user_id):
    cards = _canvas_get(DASHBOARD_CARDS_URL, params={"observed_user_id": observed_user_id})
    return [
        { "id": str(card["id"]), "name": str(card["shortName"]) }
        for card in cards
        if "id" in card
    ]

def get_submission(course_id: str, assignment_id: int, user_id: int):
    # You can add include[] here too, but start simple.
    path = f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}"
    return _canvas_get(path)[0]  # _canvas_get wraps non-list responses in a list

def get_score(course_id: str, assignment_id: int, user_id: int):
    submission = get_submission(course_id, assignment_id, user_id)
    if submission == None:
        return 0
    if 'workflow_state' in submission and submission['workflow_state'] == 'unsubmitted':
        return 0
    if not 'score' in submission or submission['score'] == None:
        return '"grading"'
    return submission['score']

def get_assignments(course_id: str, observed_user_id: int):
    # You can add include[] here too, but start simple.
    params = {
        "include[]": "submission"
    }
    assignments = _canvas_get(f"/api/v1/users/{observed_user_id}/courses/{course_id}/assignments", params=params)
    return [
            {
                "id": assignment["id"], 
                "description": assignment["description"], 
                "name": assignment["name"], 
                'due': assignment["due_at"],  
                'points_possible': assignment["points_possible"],
                'submitted': assignment["has_submitted_submissions"],
                'url': assignment["html_url"],
                # 'assignment': assignment,
                # 'submission': get_submission(course_info["id"], assignment["id"], observed_user_id)
            }
            for assignment in assignments
            if (( "due_at" in assignment and 
                _iso_to_dt(assignment["due_at"]) != None and
                _iso_to_dt(assignment["due_at"]).timestamp() < datetime.now(timezone.utc).timestamp() and
                _iso_to_dt(assignment["due_at"]).timestamp() > _iso_to_dt(CUTOFF_DATE).timestamp()) and
                ("points_possible" in assignment and
                assignment["points_possible"] is not None and
                assignment["points_possible"] > 0)) # and
                #this filtering needs to be done in the UI
                # (assignment["points_possible"] / 2) >= get_score(course_info["id"], assignment["id"], observed_user_id)))
        ]   

def get_missing_assignments(courses_info, observed_user_id):
    results = {}
    for course_info in courses_info:
        params = {
            "include[]": "submission"
        }
        assignments = _canvas_get(f"/api/v1/users/{observed_user_id}/courses/{course_info['id']}/assignments", params=params)
        print(f"Found {assignments} assignments data for user {observed_user_id}")
        results[course_info["name"]] = [
            {
                "id": assignment["id"], 
                "description": assignment["description"], 
                "name": assignment["name"], 
                'due': assignment["due_at"],  
                'points_possible': assignment["points_possible"],
                'submitted': assignment["has_submitted_submissions"],
                'url': assignment["html_url"],
            }
            for assignment in assignments
            if (( "due_at" in assignment and 
                _iso_to_dt(assignment["due_at"]) != None and
                _iso_to_dt(assignment["due_at"]).timestamp() < datetime.now(timezone.utc).timestamp() and
                _iso_to_dt(assignment["due_at"]).timestamp() > _iso_to_dt(CUTOFF_DATE).timestamp()) and
                ("points_possible" in assignment and
                assignment["points_possible"] is not None and
                assignment["points_possible"] > 0))
        ]
    return results

def lambda_handler(event, context):
    """
    Optional event overrides:
      - event["observed_user_id"]
      - event["max_items"]
    """
    params = event.get('queryStringParameters', {})
    data_type = params.get('data_type', 'html')
    results = None
    match data_type:
        case 'observees':
            print('Returning observees')
            results = _canvas_get('/api/v1/users/self/observees')
        case 'courses':
            print('Returning courses for student')
            results = get_courses(params['observed_user_id'])
        case 'assignments':
            print('Returning assignments for single student and given course')
            results = get_assignments(params['course_id'], params['observed_user_id'])
        case 'score':
            print('Returning score for course, assignment, and user')
            results = get_score(params['course_id'], params['assignment_id'], params['observed_user_id'])
        case 'html':
            print('Returning html')
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'text/html; charset=utf-8',
                    'Cache-Control': 'public, max-age=3600',#cache result for 1 hour (in browser)
                },
                'body': HTML,
            }

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json; charset=utf-8',
            'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
            'Access-Control-Allow-Methods': 'GET,OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        },
        'body': results,
    }

