"""Ready-to-send outreach copy from the user's ICP prompt."""
import re
from typing import Any, Dict


def wants_founders(prompt: str) -> bool:
    pl = prompt.lower()
    return any(w in pl for w in ("founder", "founders", "co-founder", "cofounder", "ceo"))


def _is_yc_prompt(prompt: str) -> bool:
    pl = prompt.lower()
    return "yc" in pl or "y combinator" in pl or "ycombinator" in pl


def _funding_stage(prompt: str) -> str:
    """e.g. 'Series B' from 'series b startups'."""
    m = re.search(r"series\s*([a-e])\b", prompt, re.IGNORECASE)
    if m:
        return f"Series {m.group(1).upper()}"
    return ""


def audience_phrase(prompt: str) -> str:
    """Who we're writing to — never assume YC unless the prompt says so."""
    if _is_yc_prompt(prompt):
        return "YC founders"
    stage = _funding_stage(prompt)
    if stage and wants_founders(prompt):
        return f"founders at {stage} startups"
    if wants_founders(prompt):
        return "founders"
    return ""


def _product_hint(prompt: str) -> str:
    pl = prompt.lower()
    if "saas" in pl or "b2b" in pl:
        return "B2B SaaS"
    if _is_yc_prompt(prompt):
        return "YC startups"
    # Funding stage is already in audience_phrase — don't repeat "Series B" twice.
    if _funding_stage(prompt) and wants_founders(prompt):
        return "what you're building"
    return "what you're building"


def note_has_wrong_audience(note: str, prompt: str) -> bool:
    """Detect drafts generated with the old default YC template on non-YC searches."""
    if not note or _is_yc_prompt(prompt):
        return False
    return "yc founder" in note.lower()


def _clean_company(company: str) -> str:
    c = company.strip()
    if not c:
        return ""
    return re.sub(r"\s*\([^)]*\)\s*$", "", c).strip() or c


def lead_first_name(lead: Any) -> str:
    fn = (getattr(lead, "first_name", None) or "").strip()
    if fn:
        return fn
    name = (getattr(lead, "name", None) or "").strip()
    return name.split()[0] if name else "there"


def personalize_connection(
    template: str, *, first_name: str = "", company: str = "", title: str = ""
) -> str:
    return fit_connection_note(personalize(template, first_name=first_name, company=company, title=title))


def personalize(template: str, *, first_name: str = "", company: str = "", title: str = "") -> str:
    fn = first_name.strip() or "there"
    co = _clean_company(company) or "your company"
    ti = title.strip() or "founder"
    out = template
    for key, val in (
        ("{{first_name}}", fn),
        ("{{company}}", co),
        ("{{title}}", ti),
        ("{{name}}", fn),
        ("{first_name}", fn),
        ("{company}", co),
        ("[first_name]", fn),
        ("[company]", co),
        ("[name]", fn),
    ):
        out = out.replace(key, val)
    out = re.sub(r"\bXXX\b", fn, out, flags=re.IGNORECASE)
    out = re.sub(r"\bXX\b", fn, out, flags=re.IGNORECASE)
    out = re.sub(r"\bat Carrot\b", f"at {co}", out, flags=re.IGNORECASE)
    return out


def fit_connection_note(note: str, max_len: int = 300) -> str:
    """Keep LinkedIn connection notes within the limit without mid-word cuts."""
    text = (note or "").strip()
    if len(text) <= max_len:
        return text

    for pat in (
        r"\.\s*Would love to connect[.!]?\s*$",
        r"\s+Would love to connect[.!]?\s*$",
        r"\.\s*Would love to chat[.!]?\s*$",
    ):
        shorter = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
        if shorter and len(shorter) <= max_len:
            return shorter.rstrip(".")

    if len(text) > max_len:
        cut = text[:max_len]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip("., ")
    return text


def build_outreach_kit(prompt: str, linkedin_template: str = "") -> Dict[str, Any]:
    """Templates for LinkedIn + email — filled per lead in the API/UI."""
    from services.app_settings import get_linkedin_message_templates

    saved = get_linkedin_message_templates()
    founders = wants_founders(prompt)
    product = _product_hint(prompt)
    linkedin_follow_up = saved["follow_up"]

    if linkedin_template.strip():
        linkedin = linkedin_template.strip()
        email_subject = "Quick intro — {{company}}"
        email_body = (
            "Hi {{first_name}},\n\n"
            "I came across {{company}} and wanted to reach out.\n\n"
            f"We help with {product} — happy to share more if useful.\n\n"
            "Best"
        )
    elif founders or "linkedin" in prompt.lower():
        linkedin = saved["connection"]
        audience = audience_phrase(prompt) or "founders"
        if _is_yc_prompt(prompt):
            email_subject = "YC founder → quick intro ({{company}})"
            email_body = (
                "Hi {{first_name}},\n\n"
                "I'm connecting with founders building B2B products post-YC — {{company}} stood out.\n\n"
                f"I'd love to learn more about your roadmap and share how we help teams like yours with {product}.\n\n"
                "Worth a 15-min call this week?\n\n"
                "Best"
            )
        else:
            email_subject = "Founder intro — {{company}}"
            email_body = (
                "Hi {{first_name}},\n\n"
                f"I'm connecting with {audience} — {{company}} stood out.\n\n"
                f"I'd love to learn more about your roadmap and share how we help teams like yours with {product}.\n\n"
                "Worth a 15-min call this week?\n\n"
                "Best"
            )
    else:
        linkedin = (
            "Hi {{first_name}} — saw your work at {{company}} and wanted to reach out. "
            f"Building something for teams in {product} — would value your perspective. "
            "Open to connect?"
        )
        email_subject = "Quick intro — {{company}}"
        email_body = (
            "Hi {{first_name}},\n\n"
            "I came across {{company}} and thought there could be a fit.\n\n"
            f"We help with {product} — happy to share more if useful.\n\n"
            "Best"
        )

    return {
        "linkedin_connection": linkedin,
        "linkedin_follow_up": linkedin_follow_up,
        "email_subject": email_subject,
        "email_step1": email_body,
        "email_step2": (
            "Hi {{first_name}},\n\n"
            "Following up — still think this could be valuable for {{company}}. "
            "Let me know if you'd like a quick overview.\n\n"
            "Best"
        ),
        "email_step3": (
            "Hi {{first_name}},\n\n"
            "Last note from me — happy to connect whenever timing works at {{company}}.\n\n"
            "Best"
        ),
        "channel_hint": "linkedin" if "linkedin" in prompt.lower() else "email",
        "targets_founders": founders,
    }
