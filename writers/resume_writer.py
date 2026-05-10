import os
import json
import subprocess
import shutil
import tempfile
from pathlib import Path
from loguru import logger
from openai import OpenAI

from storage import db
from brain.openai_brain import BrainOutput

BASE_DIR = Path(os.getenv("BASE_DIR", Path(__file__).parent.parent))
RESUME_TEX = BASE_DIR / "resume" / "resume_current.tex"
RESUME_PDF = BASE_DIR / "resume" / "Apoorav_latest.pdf"


def update_resume(brain_output: BrainOutput, repo_data: dict) -> str:
    """Update the LaTeX resume with brain output, compile to PDF. Returns PDF path."""
    current_tex = _load_tex()

    new_tex = _update_tex(current_tex, brain_output)
    pdf_path = _compile_tex(new_tex)

    removed = brain_output.projects_removed
    added = repo_data["repo_name"]
    summary = f"Added: {added}. Removed: {removed}. Skills: {brain_output.resume_new_skills}"

    version = db.save_resume_version(new_tex, str(pdf_path), summary)
    logger.info(f"Resume updated to version {version}: {summary}")

    for proj in brain_output.resume_projects_final:
        db.update_repo_significance(proj.name, proj.significance_score)

    return str(pdf_path)


def bootstrap_from_tex(source_tex: str) -> str:
    """One-time: load existing .tex, store in DB as version 1."""
    tex = Path(source_tex).read_text(encoding="utf-8")
    RESUME_TEX.parent.mkdir(parents=True, exist_ok=True)
    RESUME_TEX.write_text(tex, encoding="utf-8")
    db.save_resume_version(tex, source_tex, "Initial bootstrap from LaTeX source")
    logger.info(f"Resume bootstrapped from {source_tex}")
    return tex


def _load_tex() -> str:
    tex = db.get_current_resume_markdown()  # reuses the same DB column
    if not tex:
        if RESUME_TEX.exists():
            tex = RESUME_TEX.read_text(encoding="utf-8")
        else:
            raise RuntimeError("No resume .tex found — run bootstrap first")
    return tex


def _update_tex(current_tex: str, brain_output: BrainOutput) -> str:
    """Ask GPT-4o to update the LaTeX resume surgically."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    projects_json = json.dumps([
        {"name": p.name, "bullets": p.bullets, "significance": p.significance_score}
        for p in brain_output.resume_projects_final
    ], indent=2)

    prompt = f"""You are editing a LaTeX resume. The resume uses these custom commands:
- \\resumeProjectHeading{{\\textbf{{ProjectName}} $|$ \\emph{{Tech Stack}}}}{{Date}}
- \\resumeItem{{bullet text}}  (inside \\resumeItemListStart ... \\resumeItemListEnd)
- The projects section is between %-----------PROJECTS----------- and the next \\section

Here is the CURRENT LaTeX source:
<latex>
{current_tex}
</latex>

Make EXACTLY these changes:
1. Replace the entire %-----------PROJECTS----------- section content with the projects below.
   Keep the section header (\\section{{Projects}}) and the \\resumeSubHeadingListStart/End wrappers.
   Each project uses \\resumeProjectHeading and \\resumeItemListStart/End with \\resumeItem.
2. Update the Summary section text to: {brain_output.resume_summary}
3. In Technical Skills, add any new skills from this list that are not already present: {brain_output.resume_new_skills}
   Append them to the most relevant existing category line.
4. Keep EVERYTHING ELSE exactly the same — do not change Experience, Education, Achievements, Certifications, or any LaTeX preamble/commands.
5. The resume MUST fit on ONE page. Keep bullets concise (max ~15 words each).

Projects to render (in this exact order):
{projects_json}

For each project, infer the tech stack from the bullet text and format as:
\\resumeProjectHeading{{\\textbf{{ProjectName}} $|$ \\emph{{Tech1, Tech2}}}}{{}}

Return ONLY the complete updated LaTeX source, no commentary, no code fences."""

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_BRAIN_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=3500,
    )

    new_tex = resp.choices[0].message.content.strip()
    # Strip code fences if model added them
    if new_tex.startswith("```"):
        lines = new_tex.splitlines()
        new_tex = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        new_tex = new_tex.strip()

    # Validate it's actually LaTeX before returning
    if "\\documentclass" not in new_tex or "\\begin{document}" not in new_tex:
        logger.warning("GPT-4o returned non-LaTeX content — retrying once with stricter prompt")
        retry_resp = client.chat.completions.create(
            model=os.getenv("OPENAI_BRAIN_MODEL", "gpt-4o"),
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": new_tex},
                {"role": "user", "content": "Your response was not valid LaTeX. Return ONLY the raw LaTeX source starting with the comment lines and \\documentclass. No explanation, no markdown, no code fences."},
            ],
            temperature=0.1,
            max_tokens=3500,
        )
        new_tex = retry_resp.choices[0].message.content.strip()
        if new_tex.startswith("```"):
            lines = new_tex.splitlines()
            new_tex = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    if "\\documentclass" not in new_tex:
        raise RuntimeError("GPT-4o failed to return valid LaTeX after retry")

    return new_tex


def _compile_tex(tex_source: str) -> Path:
    """Compile LaTeX source to PDF using tectonic. Returns path to PDF."""
    tectonic = shutil.which("tectonic") or "/opt/homebrew/bin/tectonic"

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_file = Path(tmpdir) / "resume.tex"
        tex_file.write_text(tex_source, encoding="utf-8")

        result = subprocess.run(
            [tectonic, str(tex_file)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
            timeout=60,
        )

        if result.returncode != 0:
            logger.error(f"tectonic compilation failed:\n{result.stderr[-1000:]}")
            raise RuntimeError(f"LaTeX compilation failed: {result.stderr[-500:]}")

        compiled_pdf = Path(tmpdir) / "resume.pdf"
        if not compiled_pdf.exists():
            raise RuntimeError("tectonic ran but no PDF was produced")

        RESUME_PDF.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(compiled_pdf), str(RESUME_PDF))

    # Also write the updated .tex back to disk
    RESUME_TEX.write_text(tex_source, encoding="utf-8")
    logger.info(f"Resume compiled → {RESUME_PDF}")
    return RESUME_PDF
