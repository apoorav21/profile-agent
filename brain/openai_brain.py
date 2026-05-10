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

LINKEDIN POST — study this example and match the exact voice and structure:

EXAMPLE (do not copy, just use as style reference):
---
Most people use LLMs as a search engine.

I wanted mine to actually know what I know.

So I built an external brain — a self-compiling knowledge base where the AI reads
from your own sources, not the internet.

The idea is simple:
→ Drop articles, notes, or docs into a raw/ folder
→ Run one command
→ The AI turns them into structured wiki pages, cross-linked and searchable

The thing I find most useful: when you ask a question, the answer gets filed back
into the wiki. So the base gets smarter the more you use it — your questions become
part of the knowledge.

Currently exploring Data Engineering / ML roles where I can build systems like this.

github.com/apoorav21/project-name

What do you use to manage knowledge that actually sticks?
---

RULES:
- Open with ONE short observation about a common pattern or frustration (1 line, no fluff).
  Then pivot: "I wanted..." or "So I built..." — never open with "I built X" directly.
- NO numbered sections, NO bold headers, NO corporate structure. Write like a person
  explaining something they genuinely find interesting.
- Use "→" arrows when listing steps or features — not bullet points, not dashes.
- Short paragraphs, max 2-3 lines each. Empty line between every paragraph.
- Drop 1-2 specific technical details (library name, design decision, tradeoff) — enough
  to show depth, not enough to bore a non-engineer.
- Include the actual repo URL from the input on its own line near the end (no label, just the URL).
- End with a genuine question that invites answers — something you'd actually want to
  hear responses to. Not "Follow me!" or "What do you think?"
- Weave in one natural job signal (e.g. "exploring Data Engineering / ML roles") — not
  as a separate paragraph, just woven into the narrative.
- No decorative emojis. Only use one if it genuinely helps readability.
- Max 1000 chars. Tight is better than thorough.
- Never repeat the LinkedIn tone twice in a row.

HASHTAGS — 4-6 tags optimised for reach, appended after the post:
  Always include 1-2 high-reach tags: #Python #AI #MachineLearning #DataEngineering
    #GenerativeAI #LLM #BuildInPublic #OpenToWork #SoftwareEngineering
  Add 2-3 project-specific tags matching the actual stack: #ApacheAirflow #MediaPipe
    #FastAPI #PostgreSQL #AWS #ComputerVision #LangChain #SwiftUI #ETL etc.
  Trending engagement tags (pick 1): #BuildInPublic #100DaysOfCode #TechTwitter
  Never use low-reach generic tags like #Tech #Code #Programming #Developer

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
        max_completion_tokens=2500,
    )

    raw = response.choices[0].message.content
    logger.debug(f"Brain raw output: {raw[:500]}...")

    parsed = json.loads(raw)
    return BrainOutput(**parsed)
