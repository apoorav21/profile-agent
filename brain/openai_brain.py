import os
import json
from loguru import logger
from openai import OpenAI
from pydantic import BaseModel, Field


# ── Output schema ──────────────────────────────────────────────────────────────

class ResumeProject(BaseModel):
    name: str
    bullets: list[str] = Field(min_length=1, max_length=3)
    significance_score: int = Field(ge=1, le=10)


class BrainOutput(BaseModel):
    github_readme_section: str
    resume_summary: str
    resume_projects_final: list[ResumeProject]
    resume_new_skills: list[str]
    projects_removed: list[str]
    linkedin_post: str
    linkedin_tone: str
    linkedin_themes: list[str]
    linkedin_hashtags: list[str]
    tweet: str
    tweet_hook: str
    tweet_hashtags: list[str]
    narrative_arc_update: str


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """
You are the personal brand automation agent for Apoorav Rao, a Data Engineer and
CS student graduating June 2026 from BRCM College of Engineering & Technology.
He has 9 months experience as a Data Engineering Intern at Caterpillar Signs (Group Bayport).
Core stack: Python, SQL, PostgreSQL, AWS, Apache Airflow, Prefect, DBT, LangChain,
Django, Flask, FastAPI, Pandas, NumPy, Selenium, Git, Swift.
Target roles: Data Engineer, ML Engineer, Full-Stack Developer.
GitHub: github.com/apoorav21

=== ALL KNOWN GITHUB REPOSITORIES (pool to select best projects for resume) ===
{all_repos_json}

NOTE: The list above contains ALL known repos — not all are currently on the resume.
You decide which 4-5 best represent Apoorav's skills for target roles.

=== LINKEDIN POST HISTORY (last 20) ===
{linkedin_history}

=== TWITTER/X HISTORY (last 20) ===
{twitter_history}

=== NARRATIVE ARC ===
{narrative_arc}

=== YOUR JOB ===
When given a new repository, return a JSON object matching this exact structure:
{{
  "github_readme_section": "markdown snippet for profile README (include language badges)",
  "resume_summary": "updated 2-3 sentence professional summary highlighting top skills/projects",
  "resume_projects_final": [
    {{"name": "repo_name", "bullets": ["action verb + detail...", "action verb + metric..."], "significance_score": 8}}
  ],
  "resume_new_skills": ["skill1", "skill2"],
  "projects_removed": ["repo_name_if_any"],
  "linkedin_post": "full post text max 1200 chars",
  "linkedin_tone": "technical|achievement|story|insight",
  "linkedin_themes": ["theme1", "theme2"],
  "linkedin_hashtags": ["#Tag1", "#Tag2", "#Tag3"],
  "tweet": "tweet text WITHOUT hashtags or link (those are appended separately)",
  "tweet_hook": "problem-solution|achievement|question|insight",
  "tweet_hashtags": ["#tag1", "#tag2", "#tag3"],
  "narrative_arc_update": "1-2 sentence updated arc"
}}

=== STRICT RULES ===
RESUME:
- resume_projects_final MUST be the 4-5 BEST projects chosen from ALL known repos above,
  not just the currently displayed ones. Re-evaluate the entire pool each time.
- The resume MUST fit exactly ONE page. Maximum 4-5 projects total.
- Score every project 1-10: recency (recent=higher), technical complexity,
  impact/novelty, relevance to target roles (Data Eng / ML / Full-Stack).
- Keep the highest-scoring 4-5. If the new repo scores higher than any current project,
  swap it in by removing the lowest scorer.
- Always rewrite the resume_summary to reflect the strongest current projects and skills.
- Resume bullets: strong action verbs, specific technologies, scale or metric.
  Example: "Built real-time sign language translator using MediaPipe + CNN achieving
  94% accuracy on 26 ASL gestures."
- Add to resume_new_skills any tech from the new repo not already in the skills section.

LINKEDIN POST (CRITICAL — Apoorav is actively job-seeking):
- This post must read like a technical showcase for recruiters and hiring managers.
- Structure: (1) Hook — open with the specific technical PROBLEM or challenge.
  (2) Solution — explain WHICH technologies you chose and WHY (not just what you built).
  (3) Architecture — describe how the key components fit together (2-3 sentences).
  (4) Result — include a concrete metric or outcome if available.
  (5) CTA — end with "Open to Data Engineer / ML Engineer roles" or similar job signal.
- Name-drop specific tools, libraries, frameworks, and design decisions.
  Example: "I chose Apache Airflow over cron because I needed DAG-level retry logic
  and real-time monitoring via Prefect."
- Max 1200 chars. Tone: technical but readable (not academic).
- Include 3-5 hashtags mixing broad (#Python, #DataEngineering) with role-signal tags
  (#HiringDataEngineers, #OpenToWork, #MLEngineer).
- Never repeat the LinkedIn tone twice in a row.

TWEET:
- Punchy standalone insight. Max 200 chars (link + hashtags added separately).
  No em-dashes. Direct and confident.
- Never repeat the tweet_hook type used in the last 3 tweets.
- Hashtags: 3-5, mix broad and niche (#buildinpublic, #DataEngineering).

GITHUB README:
- Include shields.io badge for primary language and any other relevant badges.
- 2-3 sentences max. Concise and scannable.
""".strip()


# ── Main function ──────────────────────────────────────────────────────────────

def generate(repo_data: dict, context: dict) -> BrainOutput:
    """Generate all outputs for a newly detected repository."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_BRAIN_MODEL", "gpt-4o")

    all_repos = context.get("all_repos", [])
    linkedin_posts = context.get("recent_linkedin_posts", [])
    tweets = context.get("recent_tweets", [])
    narrative_arc = context.get("narrative_arc", "No posts made yet.")

    # Serialize context for system prompt
    repos_summary = json.dumps([
        {
            "name": r["repo_name"],
            "description": r.get("description", ""),
            "language": r.get("language", ""),
            "key_features": json.loads(r["key_features"]) if r.get("key_features") else [],
            "significance_score": r.get("significance", 5),
        }
        for r in all_repos
    ], indent=2)

    li_history = json.dumps([
        {"text": p["post_text"][:300], "tone": p.get("tone"), "themes": p.get("themes")}
        for p in linkedin_posts
    ], indent=2)

    tw_history = json.dumps([
        {"text": t["tweet_text"][:200], "hook": t.get("hook_type")}
        for t in tweets
    ], indent=2)

    system_prompt = _SYSTEM_TEMPLATE.format(
        all_repos_json=repos_summary,
        linkedin_history=li_history or "[]",
        twitter_history=tw_history or "[]",
        narrative_arc=narrative_arc,
    )

    repo_input = json.dumps({
        "repo_name": repo_data["repo_name"],
        "description": repo_data.get("description", ""),
        "language": repo_data.get("language", ""),
        "languages": repo_data.get("languages", {}),
        "topics": repo_data.get("topics", []),
        "key_features": repo_data.get("key_features", []),
        "stars": repo_data.get("stars", 0),
        "readme_excerpt": (repo_data.get("readme_md") or "")[:2000],
        "url": repo_data.get("url", ""),
    }, indent=2)

    logger.info(f"Calling OpenAI brain for repo: {repo_data['repo_name']}")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"New repository detected:\n{repo_input}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=2500,
    )

    raw = response.choices[0].message.content
    logger.debug(f"Brain raw output: {raw[:500]}...")

    parsed = json.loads(raw)
    return BrainOutput(**parsed)
