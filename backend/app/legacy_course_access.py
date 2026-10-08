"""Non-updating rights use the existing courses, with an explicit material baseline."""
from copy import deepcopy

LEGACY_COURSES = {
    "ACCESS_MASTERCLASS": "ACCESS_MASTERCLASS_LEGACY",
    "ACCESS_CALORIES": "ACCESS_CALORIES_LEGACY",
}

# The owner's approved baseline is explicit: newly published steps stay closed.
MASTERCLASS_BASELINE = frozenset({
    "day-01-article-tutorial", "day-01-article-02", "day-01-messenger-link",
    "day-01-article-03", "day-01-questionnaire", "day-01-offer",
    "day-02-article-01", "day-02-article-02", "day-02-current-diet",
    "day-03-video-01", "day-03-article-02", "day-03-article-03",
    "day-04-article-01", "day-05-article-01", "day-05-article-03",
    "day-06-offer", "day-09-article-01",
    "day-10-article-01", "day-10-article-02", "day-10-article-03",
    "day-11-article-01", "day-11-article-02", "day-12-article-01",
    "day-12-article-02", "day-13-article-01", "day-13-article-02",
    "day-14-article-01", "day-14-offer", "day-15-article-02",
    "day-18-article-02", "day-16-offer",
    "day-17-article-01", "day-17-article-02", "day-17-article-03",
    "day-20-article-01", "day-20-article-02", "day-19-closing-review",
    "day-19-article-02", "day-19-offer", "day-21-article-01", "day-21-offer",
})
RECIPE_MATERIALS = frozenset({
    "day-06-article-01", "day-06-article-02", "day-06-rule-1-percent",
    "day-06-article-03", "day-07-video-01", "day-07-recipes-part-1",
    "day-07-store-food", "day-15-recipes-part-2",
})


def course_resource(owned: set[str], code: str) -> str:
    return code if code in owned else LEGACY_COURSES.get(code, code)


def has_course(owned: set[str], code: str) -> bool:
    return course_resource(owned, code) in owned


def legacy_masterclass_manifest(manifest: dict, owned: set[str]) -> dict:
    if "ACCESS_MASTERCLASS" in owned or "ACCESS_MASTERCLASS_LEGACY" not in owned:
        return manifest
    result = deepcopy(manifest)
    result["accessEdition"] = "non_updating"
    for day in result.get("days", []):
        # Show each title in the same course instead of replacing recipe days by a sale.
        day.pop("accessResource", None)
        day["accessDenied"] = False
        for step in day.get("steps", []):
            ident = str(step.get("id") or "")
            recipe = ident in RECIPE_MATERIALS or bool(step.get("nested") and step.get("parentStepId") == "day-15-recipes-part-2")
            allowed = ident in MASTERCLASS_BASELINE or (recipe and "ACCESS_RECIPES" in owned)
            if not allowed and not step.get("hidden"):
                step.update(locked=True, required=False, legacyLocked=True,
                            badge="В обновляемом доступе",
                            accessExplanation="Материал доступен в обновляемом доступе.")
                step.pop("contentAsset", None)
                step.pop("contentPageTitle", None)
        # Tasks referring to a locked tool cannot be required to finish the day.
        if int(day["number"]) in {4, 6, 7, 8, 15}:
            day["checks"] = [{"id": f"legacy-day-{day['number']}-review",
                              "text": "Изучите доступные материалы дня и запишите выводы в дневник.",
                              "required": True}]
            day["taskIntroHtml"] = ""
    return result
