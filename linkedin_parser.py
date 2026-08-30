from __future__ import annotations


def _t(entity: dict) -> str:
    """Short type name, e.g. 'com.linkedin...Position' -> 'Position'."""
    return entity.get("$type", "").split(".")[-1]


def _date_range(dr: dict | None) -> str | None:
    if not dr:
        return None

    def fmt(d):
        if not d:
            return None
        y, m = d.get("year"), d.get("month")
        return f"{y}-{m:02d}" if (y and m) else (str(y) if y else None)

    start, end = fmt(dr.get("start")), fmt(dr.get("end"))
    if start and end:
        return f"{start} – {end}"
    if start:
        return f"{start} – Present"
    return end


def _photo(profile: dict) -> str | None:
    """Best profile-photo URL from the nested VectorImage (rootUrl + artifacts)."""
    def dig(o):
        if isinstance(o, dict):
            if "rootUrl" in o and "artifacts" in o:
                return o
            for v in o.values():
                found = dig(v)
                if found:
                    return found
        return None

    vi = dig(profile.get("profilePicture") or {})
    if not vi:
        return None
    artifacts = vi.get("artifacts") or []
    if not artifacts:
        return None
    best = max(artifacts, key=lambda a: a.get("width", 0))
    seg = best.get("fileIdentifyingUrlPathSegment", "")
    return vi["rootUrl"] + seg if seg else None


def _location(profile: dict, included: list[dict]) -> str | None:
    direct = profile.get("locationName") or profile.get("geoLocationName")
    if direct:
        return direct
    geo_ref = profile.get("geoLocation") or {}
    geo_urn = geo_ref.get("*geo") if isinstance(geo_ref, dict) else None
    for e in included:
        if _t(e) == "Geo" and (e.get("entityUrn") == geo_urn or not geo_urn):
            name = (
                e.get("defaultLocalizedName")
                or e.get("localizedName")
                or e.get("name")
            )
            if name:
                return name
    return None


def _find_profile(included: list[dict], member_id: str) -> dict:
    return next(
        (e for e in included if _t(e) == "Profile" and member_id in e.get("entityUrn", "")),
        next((e for e in included if _t(e) == "Profile"), {}),
    )


def parse_profile(included: list[dict], member_id: str) -> dict:
    """Turn a Voyager ``included`` array into a clean profile dict."""
    profile = _find_profile(included, member_id)

    def scoped(type_name: str) -> list[dict]:
        return [e for e in included if _t(e) == type_name]

    experience = [{
        "title": p.get("title"),
        "company": p.get("companyName"),
        "employment_type": p.get("employmentType"),
        "location": p.get("locationName"),
        "date_range": _date_range(p.get("dateRange")),
        "description": p.get("description"),
    } for p in scoped("Position")]

    education = [{
        "school": ed.get("schoolName"),
        "degree": ed.get("degreeName"),
        "field_of_study": ed.get("fieldOfStudy"),
        "grade": ed.get("grade"),
        "date_range": _date_range(ed.get("dateRange")),
    } for ed in scoped("Education")]

    skills = [s.get("name") for s in scoped("Skill") if s.get("name")]

    certifications = [{
        "name": c.get("name"),
        "authority": c.get("authority"),
        "license_number": c.get("licenseNumber"),
        "url": c.get("url"),
    } for c in scoped("Certification")]

    languages = [{
        "name": ln.get("name"),
        "proficiency": ln.get("proficiency"),
    } for ln in scoped("Language")]

    return {
        "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
        "first_name": profile.get("firstName"),
        "last_name": profile.get("lastName"),
        "headline": profile.get("headline"),
        "location": _location(profile, included),
        "about": profile.get("summary"),
        "profile_photo": _photo(profile),
        "experience": experience,
        "education": education,
        "skills": skills,
        "certifications": certifications,
        "languages": languages,
    }