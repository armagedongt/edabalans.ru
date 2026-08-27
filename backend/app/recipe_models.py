from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import TimestampMixin, uuid_pk


class NutritionProduct(TimestampMixin, Base):
    __tablename__ = "nutrition_products"
    __table_args__ = (
        Index("ix_nutrition_products_catalog_search", "owner_user_id", "is_active", "name_normalized"),
        UniqueConstraint("source_url", name="uq_nutrition_product_source_url"),
        CheckConstraint("protein_g >= 0 AND fat_g >= 0 AND carbohydrate_g >= 0 AND calories_kcal >= 0", name="ck_nutrition_product_nonnegative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    protein_g: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    fat_g: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    carbohydrate_g: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    calories_kcal: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)


class RecipeBook(TimestampMixin, Base):
    __tablename__ = "recipe_books"
    __table_args__ = (
        Index("ix_recipe_books_owner_active", "owner_user_id", "deleted_at", "updated_at"),
        CheckConstraint("shrinkage_g >= 0", name="ck_recipe_book_shrinkage_nonnegative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    shrinkage_g: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        Index("ix_recipe_ingredients_recipe_order", "recipe_id", "sort_order"),
        Index("ix_recipe_ingredients_nested_recipe", "nested_recipe_id"),
        CheckConstraint("weight_g > 0", name="ck_recipe_ingredient_weight_positive"),
        CheckConstraint("(nutrition_product_id IS NOT NULL) <> (nested_recipe_id IS NOT NULL)", name="ck_recipe_ingredient_single_source"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipe_books.id", ondelete="CASCADE"), index=True)
    nutrition_product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("nutrition_products.id", ondelete="RESTRICT"))
    nested_recipe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recipe_books.id", ondelete="RESTRICT"))
    weight_g: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
