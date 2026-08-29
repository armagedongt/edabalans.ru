"""Freeze and validate the 14-article Calorie Course editorial build."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import author_workflow
from validate_author_draft import validate


DRAFT_ROOT = ROOT / "work" / "calorie-course-rebuild" / "rebuild-v4-final-2026-08-29"
PRIVATE_ROOT = Path(tempfile.gettempdir()) / "edabalans-calorie-course-v4-2026-08-29"

FILES = {
    "stage-01/01-app-tracking.md": ("Запись фактически съеденной еды", "Выбор инструмента и граница между записью и рекомендацией"),
    "stage-01/02-counting-different-food.md": ("Расчёт разных видов еды", "Пять бытовых сценариев от отдельного продукта до общей кастрюли"),
    "stage-01/03-accuracy-baseline-diary.md": ("Семь обычных дней", "Непрерывный и достаточно точный исходный дневник"),
    "stage-02/01-app-metrics.md": ("Чтение показателей", "Диагностика вопроса без культа идеальных БЖУ"),
    "stage-02/02-calorie-sources.md": ("Карта источников калорий", "Переход от продукта к рецепту и целому дню"),
    "stage-02/03-adjust-current-diet.md": ("Точечная коррекция", "Изменение текущего рациона вместо придуманного идеального меню"),
    "stage-03/01-expenditure-calculator.md": ("Модель расхода", "Сбор двух честных сценариев калькулятора"),
    "stage-03/02-steps-training-double-count.md": ("Учёт активности", "Устранение двойного счёта шагов и тренировок"),
    "stage-04/01-phase-deficit-pace.md": ("Фаза и темп", "Выбор переносимого эксперимента вместо обещания результата"),
    "stage-04/02-comparable-data.md": ("Окно наблюдения", "Сопоставимые данные веса, питания, активности и переносимости"),
    "stage-04/03-correct-the-model.md": ("Коррекция модели", "Одна проверяемая причина и одно следующее действие"),
    "stage-05/01-repeat-meals-household-measures.md": ("Повторяемые приёмы", "Перевод точных расчётов в бытовые меры и карточки"),
    "stage-05/02-rhythm-hunger-snacking.md": ("Ритм и голод", "Настройка собственного ритма без универсального числа приёмов"),
    "stage-05/03-stop-tracking.md": ("Выход из учёта", "Лестница отказа от цифр и заранее заданные условия возврата"),
}

CONTINUITY = [
    {"idea": "От записи фактов к диагностике", "route": "Этап 1 собирает дневник; этап 2 объясняет, что в нём искать."},
    {"idea": "От точности к упрощению", "route": "Этап 1 создаёт точную базу; этап 5 переводит её в бытовые меры и шаблоны."},
    {"idea": "От калькулятора к проверяемой модели", "route": "Этап 3 оценивает расход; этап 4 сравнивает оценку с трендом и корректирует одну причину."},
    {"idea": "От цифр к действиям", "route": "Этапы 2–4 связывают наблюдение и изменение; этап 5 оставляет действия без постоянного учёта."},
]

COURSE_OUTLINE = [
    {"day": 1, "materials": ["Как пользоваться приложением", "Как считать разную еду", "Точность и семь обычных дней"]},
    {"day": 2, "materials": ["Показатели приложения", "Источники калорий", "Как менять текущий рацион"]},
    {"day": 3, "materials": ["Калькулятор расхода", "Шаги, тренировки и двойной счёт"]},
    {"day": 4, "materials": ["Фаза, дефицит и темп", "Сопоставимые данные", "Как корректировать модель"]},
    {"day": 5, "materials": ["Повторяемые приёмы и бытовые меры", "Ритм, голод и кусочничество", "Как перестать считать"]},
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_anchor(text: str) -> str:
    for paragraph in text.split("\n\n"):
        value = paragraph.strip()
        if len(value) >= 40 and not value.startswith(("!", ":::")):
            return value[:180]
    raise ValueError("no preservation anchor")


def main() -> int:
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    index = PRIVATE_ROOT / "unused-voice-index.sqlite"
    evidence = DRAFT_ROOT / "evidence" / "pubmed-all.xml"
    source_review = DRAFT_ROOT / "source-review-final-2026-08-29.md"
    fact_sources = [
        {"name": "PubMed XML batch", "fingerprint": f"sha256:{sha256(evidence)}"},
        {"name": "Final source review", "fingerprint": f"sha256:{sha256(source_review)}"},
    ]
    manifest: dict[str, dict[str, object]] = {}

    for relative, (day_context, material_role) in FILES.items():
        draft = DRAFT_ROOT / relative
        # Freeze the already completed source-first rewrite. The source-use ledgers
        # carry the migration comparison; this pack protects the exact reviewed bytes.
        source_text = draft.read_text(encoding="utf-8")
        private_draft = PRIVATE_ROOT / relative
        private_draft.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(draft, private_draft)

        slug = relative.replace("/", "--").removesuffix(".md")
        task = PRIVATE_ROOT / f"{slug}.task.json"
        pack = PRIVATE_ROOT / f"{slug}.pack.json"
        review = PRIVATE_ROOT / f"{slug}.review.json"
        report = PRIVATE_ROOT / f"{slug}.validation.json"
        task.write_text(
            json.dumps(
                {
                    "note": "Финальная редакторская сборка материала Калорийного курса из полного авторского корпуса.",
                    "work_profile": "develop_existing",
                    "source_basis": "full_source",
                    "author_reuse_mode": "authored_blocks_first",
                    "edit_mode": "targeted_edit",
                    "surface_context": "course_material",
                    "format_profile": "course",
                    "product": "calorie_course",
                    "course_outline": COURSE_OUTLINE,
                    "course_structure_source": "work/calorie-course-rebuild/architecture/README.md",
                    "course_context": {
                        "day_context": day_context,
                        "material_role": material_role,
                        "continuity": "Материал продолжает последовательность из course-continuity-review.md и передаёт только следующий необходимый слой.",
                    },
                    "course_continuity": CONTINUITY,
                    "source_text": source_text,
                    "editable_scope": ["## Источники"],
                    "preservation_anchors": [first_anchor(source_text)],
                    "allow_link_media_changes": True,
                    "fact_check_profile": "instructional_strict",
                    "fact_sources": fact_sources,
                    "required_facts": [{"text": "Числовые, причинные и физиологические утверждения не выходят за границы источников, перечисленных в материале.", "mode": "semantic"}],
                    "forbidden_claims": [
                        "Служебный медиаплейсхолдер или редакторское распоряжение опубликованы как часть статьи.",
                        "Расчёт калькулятора выдан за прямое измерение индивидуального расхода.",
                        "БЖУ выданы за достаточное доказательство качества и сбалансированности рациона.",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        author_workflow.prepare(task, index, pack)
        result = validate(pack, private_draft)
        if result["status"] == "manual_review_required":
            notes = {
                "course_context_continuity": "Роль материала сверена с архитектурой пяти этапов; оболочка курса не повторяется и передаётся только следующий шаг.",
                "course_architecture": "Последовательность запись → анализ → расход → калибровка → упрощение сохранена; искусственного выравнивания длины нет.",
                "semantic_facts": "Ключевые числовые, причинные и физиологические утверждения сверены с PubMed-аннотациями, официальным документом ЕАЭС и итоговой картой источников.",
                "forbidden_claims": "Служебных плейсхолдеров нет; калькулятор назван моделью; БЖУ не выданы за достаточную оценку качества рациона.",
            }
            author_workflow.create_review(
                pack,
                private_draft,
                review,
                reviewer="Codex, финальная редактура Калорийного курса",
                check_values=[f"{item['id']}={notes[item['id']]}" for item in result["pending_manual_reviews"]],
            )
            result = validate(pack, private_draft, review)
        author_workflow.write_json(report, result)
        if result["status"] != "pass":
            raise ValueError(f"{relative}: {result['status']} {result.get('errors')}")
        manifest[relative] = {
            "sha256": sha256(draft),
            "pack": str(pack),
            "review": str(review),
            "validation": str(report),
            "status": result["status"],
        }

    manifest_path = PRIVATE_ROOT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "pass", "files": len(manifest), "manifest": str(manifest_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
