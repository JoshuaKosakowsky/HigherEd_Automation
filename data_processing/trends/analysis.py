from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from data_processing.shared.tgiaccd import (
    fiscal_year_from_filename,
    iter_tgiaccd_rows,
)

from .config import (
    ANNUAL_EXACT_REPORTING_GROUPS,
    REQUIRED_COLUMNS,
    TrendsConfig,
)


@dataclass
class DetailCodeTotal:
    fiscal_year: int
    detail_code: str
    description: str
    code_type: str
    category: str
    transaction_count: int = 0
    total_amount: float = 0.0
    signed_ar_effect: float = 0.0
    student_ids: set[str] = field(
        default_factory=set,
        repr=False,
    )

    @property
    def student_count(self) -> int:
        return len(self.student_ids)


@dataclass
class TermDetailCodeTotal:
    fiscal_year: int
    term: str
    detail_code: str
    description: str
    code_type: str
    category: str
    transaction_count: int
    student_count: int
    total_amount: float

    @property
    def signed_ar_effect(self) -> float:
        if self.code_type == "C":
            return self.total_amount
        if self.code_type == "P":
            return -self.total_amount
        return 0.0


@dataclass
class ChargeAverage:
    fiscal_year: int
    label: str
    category_codes: str
    transaction_count: int
    charge_transaction_count: int
    payment_credit_transaction_count: int
    student_count_with_activity: int
    all_student_count: int
    charge_amount: float
    payment_credit_amount: float

    @property
    def net_category_amount(self) -> float:
        return (
            self.charge_amount
            - self.payment_credit_amount
        )

    @property
    def average_per_student_with_activity(
        self,
    ) -> float:
        if self.student_count_with_activity == 0:
            return 0.0

        return (
            self.net_category_amount
            / self.student_count_with_activity
        )

    @property
    def average_per_all_students(self) -> float:
        if self.all_student_count == 0:
            return 0.0

        return (
            self.net_category_amount
            / self.all_student_count
        )

@dataclass(frozen=True)
class ReportingGroupTotal:
    fiscal_year: int
    label: str
    included_codes: str
    transaction_count: int
    charge_transaction_count: int
    payment_credit_transaction_count: int
    student_count_with_activity: int
    all_student_count: int
    charge_amount: float
    payment_credit_amount: float
    net_amount: float

@dataclass
class TermGroupTotal:
    fiscal_year: int
    term: str
    label: str
    included_codes: str
    transaction_count: int
    charge_transaction_count: int
    payment_credit_transaction_count: int
    student_count_with_activity: int
    students_in_term: int
    charge_amount: float
    payment_credit_amount: float

    @property
    def net_amount(self) -> float:
        return (
            self.charge_amount
            - self.payment_credit_amount
        )


@dataclass
class CategoryAccumulator:
    transaction_count: int = 0
    charge_transaction_count: int = 0
    payment_credit_transaction_count: int = 0
    charge_amount: float = 0.0
    payment_credit_amount: float = 0.0
    student_net_amounts: dict[
        str,
        float,
    ] = field(
        default_factory=lambda: defaultdict(float)
    )

    def add(
        self,
        *,
        student_id: str,
        code_type: str,
        amount: float,
    ) -> None:
        self.transaction_count += 1

        if code_type == "C":
            self.charge_transaction_count += 1
            self.charge_amount += amount
            signed_amount = amount
        elif code_type == "P":
            self.payment_credit_transaction_count += 1
            self.payment_credit_amount += amount
            signed_amount = -amount
        else:
            return

        if student_id:
            self.student_net_amounts[
                student_id
            ] += signed_amount


@dataclass
class DetailCodeAccumulator:
    transaction_count: int = 0
    total_amount: float = 0.0
    student_ids: set[str] = field(
        default_factory=set
    )

    def add(
        self,
        *,
        student_id: str,
        amount: float,
    ) -> None:
        self.transaction_count += 1
        self.total_amount += amount

        if student_id:
            self.student_ids.add(student_id)


@dataclass
class FiscalYearAnalysis:
    fiscal_year: int
    source_file: str
    row_count: int = 0
    student_ids: set[str] = field(
        default_factory=set
    )
    positive_ar_student_ids: set[str] = field(
        default_factory=set
    )
    nonzero_balance_student_ids: set[str] = field(
        default_factory=set
    )
    writeoff_student_ids: set[str] = field(
        default_factory=set
    )
    charge_activity: float = 0.0
    payment_credit_activity: float = 0.0
    net_ar_activity: float = 0.0
    gross_ar: float = 0.0
    credit_balances: float = 0.0
    net_ar: float = 0.0
    gross_tuition_charges: float = 0.0
    tuition_offsets: float = 0.0
    net_tuition_revenue: float = 0.0
    writeoff_count: int = 0
    writeoff_amount: float = 0.0
    mapped_row_count: int = 0
    unmapped_row_count: int = 0
    unmapped_detail_codes: set[str] = field(
        default_factory=set
    )

    @property
    def student_count(self) -> int:
        return len(self.student_ids)

    @property
    def positive_ar_student_count(self) -> int:
        return len(
            self.positive_ar_student_ids
        )

    @property
    def nonzero_balance_student_count(self) -> int:
        return len(
            self.nonzero_balance_student_ids
        )

    @property
    def writeoff_student_count(self) -> int:
        return len(self.writeoff_student_ids)

    @property
    def average_positive_balance(self) -> float:
        if self.positive_ar_student_count == 0:
            return 0.0

        return (
            self.gross_ar
            / self.positive_ar_student_count
        )

    @property
    def average_net_balance_all_students(self) -> float:
        if self.student_count == 0:
            return 0.0

        return self.net_ar / self.student_count


@dataclass(frozen=True)
class TrendsFileAnalysisResult:
    fiscal_year: FiscalYearAnalysis
    detail_codes: list[DetailCodeTotal]
    group_averages: list[ChargeAverage]
    category_averages: list[ChargeAverage]
    term_groups: list[TermGroupTotal]
    term_collections: list[TermDetailCodeTotal]


@dataclass(frozen=True)
class TrendsAnalysisResult:
    fiscal_years: list[FiscalYearAnalysis]
    detail_codes: list[DetailCodeTotal]
    group_averages: list[ChargeAverage]
    category_averages: list[ChargeAverage]
    term_groups: list[TermGroupTotal]
    term_collections: list[TermDetailCodeTotal]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_amount(value: object) -> float:
    if value in {None, ""}:
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Expected a numeric amount; received {value!r}."
        ) from error


def analyze_tgiaccd_file(
    path: Path,
    *,
    detail_codes: dict[str, dict[str, object]],
    config: TrendsConfig,
) -> TrendsFileAnalysisResult:
    """
    Calculate fiscal-year and detail-code statistics.
    """
    fiscal_year = fiscal_year_from_filename(
        path
    )
    analysis = FiscalYearAnalysis(
        fiscal_year=fiscal_year,
        source_file=path.name,
    )
    detail_totals: dict[str, DetailCodeTotal] = {}
    category_accumulators: dict[
        str,
        CategoryAccumulator,
    ] = defaultdict(CategoryAccumulator)
    group_accumulators: dict[
        str,
        CategoryAccumulator,
    ] = {
        group_name: CategoryAccumulator()
        for group_name, _ in config.charge_groups
    }
    term_student_ids: dict[
        str,
        set[str],
    ] = defaultdict(set)
    observed_terms: set[str] = set()
    term_group_accumulators: dict[
        tuple[str, str],
        CategoryAccumulator,
    ] = defaultdict(CategoryAccumulator)
    term_writeoff_accumulators: dict[
        str,
        CategoryAccumulator,
    ] = defaultdict(CategoryAccumulator)
    collection_terms: set[str] = set()
    term_collection_accumulators: dict[
        tuple[str, str],
        DetailCodeAccumulator,
    ] = defaultdict(DetailCodeAccumulator)
    groups_by_category: dict[
        str,
        list[str],
    ] = defaultdict(list)

    for group_name, categories in config.charge_groups:
        for category_code in categories:
            groups_by_category[
                category_code
            ].append(group_name)

    for row in iter_tgiaccd_rows(
        path,
        required_columns=REQUIRED_COLUMNS,
    ):
        analysis.row_count += 1

        student_id = _clean_text(
            row["ID"]
        )
        detail_code = _clean_text(
            row["Detail Code"]
        ).upper()
        description = _clean_text(
            row["Description"]
        )
        amount = _clean_amount(
            row["Amount"]
        )
        balance = _clean_amount(
            row["Balance"]
        )
        term = (
            _clean_text(row["Term"])
            or "(No Term)"
        )
        observed_terms.add(term)

        if student_id:
            analysis.student_ids.add(
                student_id
            )
            term_student_ids[term].add(
                student_id
            )

        if balance > 0:
            analysis.gross_ar += balance
            if student_id:
                analysis.positive_ar_student_ids.add(
                    student_id
                )
                analysis.nonzero_balance_student_ids.add(
                    student_id
                )
        elif balance < 0:
            analysis.credit_balances += balance
            if student_id:
                analysis.nonzero_balance_student_ids.add(
                    student_id
                )

        analysis.net_ar += balance

        metadata = detail_codes.get(
            detail_code
        )

        if metadata is None:
            analysis.unmapped_row_count += 1
            analysis.unmapped_detail_codes.add(
                detail_code or "<blank>"
            )
            code_type = ""
            category = ""
        else:
            analysis.mapped_row_count += 1
            code_type = _clean_text(
                metadata.get("type")
            ).upper()
            category = _clean_text(
                metadata.get("category")
            ).upper()

        if code_type == "C":
            signed_ar_effect = amount
            analysis.charge_activity += amount
            analysis.net_ar_activity += amount
        elif code_type == "P":
            signed_ar_effect = -amount
            analysis.payment_credit_activity += amount
            analysis.net_ar_activity -= amount
        else:
            signed_ar_effect = 0.0

        if (
            category
            and code_type in {"C", "P"}
        ):
            category_accumulators[
                category
            ].add(
                student_id=student_id,
                code_type=code_type,
                amount=amount,
            )

            for group_name in groups_by_category[
                category
            ]:
                group_accumulators[
                    group_name
                ].add(
                    student_id=student_id,
                    code_type=code_type,
                    amount=amount,
                )
                term_group_accumulators[
                    (term, group_name)
                ].add(
                    student_id=student_id,
                    code_type=code_type,
                    amount=amount,
                )

        if category == config.tuition_category:
            if code_type == "C":
                analysis.gross_tuition_charges += amount
                analysis.net_tuition_revenue += amount
            elif code_type == "P":
                analysis.tuition_offsets += amount
                analysis.net_tuition_revenue -= amount

        if detail_code == config.writeoff_code:
            analysis.writeoff_count += 1
            analysis.writeoff_amount += amount
            term_writeoff_accumulators[
                term
            ].add(
                student_id=student_id,
                code_type=code_type,
                amount=amount,
            )
            if student_id:
                analysis.writeoff_student_ids.add(
                    student_id
                )

        if detail_code in config.collection_codes:
            collection_terms.add(term)
            term_collection_accumulators[
                (term, detail_code)
            ].add(
                student_id=student_id,
                amount=amount,
            )

        detail_total = detail_totals.setdefault(
            detail_code,
            DetailCodeTotal(
                fiscal_year=fiscal_year,
                detail_code=detail_code,
                description=(
                    _clean_text(
                        metadata.get(
                            "detail_code_description"
                        )
                    )
                    if metadata
                    else description
                ),
                code_type=code_type,
                category=category,
            ),
        )

        detail_total.transaction_count += 1
        detail_total.total_amount += amount
        detail_total.signed_ar_effect += (
            signed_ar_effect
        )
        if student_id:
            detail_total.student_ids.add(
                student_id
            )

    if (
        config.strict_detail_codes
        and analysis.unmapped_detail_codes
    ):
        raise ValueError(
            f"{path.name} contains detail codes missing "
            "from the reference file: "
            f"{sorted(analysis.unmapped_detail_codes)}"
        )

    category_averages = [
        ChargeAverage(
            fiscal_year=fiscal_year,
            label=category,
            category_codes=category,
            transaction_count=accumulator.transaction_count,
            charge_transaction_count=(
                accumulator.charge_transaction_count
            ),
            payment_credit_transaction_count=(
                accumulator.payment_credit_transaction_count
            ),
            student_count_with_activity=len(
                accumulator.student_net_amounts
            ),
            all_student_count=analysis.student_count,
            charge_amount=accumulator.charge_amount,
            payment_credit_amount=(
                accumulator.payment_credit_amount
            ),
        )
        for category, accumulator
        in sorted(
            category_accumulators.items()
        )
    ]

    group_averages = [
        ChargeAverage(
            fiscal_year=fiscal_year,
            label=group_name,
            category_codes=", ".join(categories),
            transaction_count=(
                group_accumulators[
                    group_name
                ].transaction_count
            ),
            charge_transaction_count=(
                group_accumulators[
                    group_name
                ].charge_transaction_count
            ),
            payment_credit_transaction_count=(
                group_accumulators[
                    group_name
                ].payment_credit_transaction_count
            ),
            student_count_with_activity=len(
                group_accumulators[
                    group_name
                ].student_net_amounts
            ),
            all_student_count=analysis.student_count,
            charge_amount=(
                group_accumulators[
                    group_name
                ].charge_amount
            ),
            payment_credit_amount=(
                group_accumulators[
                    group_name
                ].payment_credit_amount
            ),
        )
        for group_name, categories
        in config.charge_groups
    ]

    def term_sort_key(term: str) -> tuple[bool, str]:
        return (term == "(No Term)", term)

    term_group_totals: list[TermGroupTotal] = []

    for term in sorted(
        observed_terms,
        key=term_sort_key,
    ):
        students_in_term = len(
            term_student_ids[term]
        )

        for group_name, categories in config.charge_groups:
            accumulator = term_group_accumulators[
                (term, group_name)
            ]
            term_group_totals.append(
                TermGroupTotal(
                    fiscal_year=fiscal_year,
                    term=term,
                    label=group_name,
                    included_codes=", ".join(categories),
                    transaction_count=(
                        accumulator.transaction_count
                    ),
                    charge_transaction_count=(
                        accumulator.charge_transaction_count
                    ),
                    payment_credit_transaction_count=(
                        accumulator.payment_credit_transaction_count
                    ),
                    student_count_with_activity=len(
                        accumulator.student_net_amounts
                    ),
                    students_in_term=students_in_term,
                    charge_amount=accumulator.charge_amount,
                    payment_credit_amount=(
                        accumulator.payment_credit_amount
                    ),
                )
            )

        writeoff_accumulator = (
            term_writeoff_accumulators[term]
        )
        term_group_totals.append(
            TermGroupTotal(
                fiscal_year=fiscal_year,
                term=term,
                label="WOFF",
                included_codes="Detail Code: WOFF",
                transaction_count=(
                    writeoff_accumulator.transaction_count
                ),
                charge_transaction_count=(
                    writeoff_accumulator.charge_transaction_count
                ),
                payment_credit_transaction_count=(
                    writeoff_accumulator.payment_credit_transaction_count
                ),
                student_count_with_activity=len(
                    writeoff_accumulator.student_net_amounts
                ),
                students_in_term=students_in_term,
                charge_amount=(
                    writeoff_accumulator.charge_amount
                ),
                payment_credit_amount=(
                    writeoff_accumulator.payment_credit_amount
                ),
            )
        )

    term_collection_totals: list[
        TermDetailCodeTotal
    ] = []

    for term in sorted(
        collection_terms,
        key=term_sort_key,
    ):
        for detail_code in config.collection_codes:
            accumulator = term_collection_accumulators[
                (term, detail_code)
            ]
            metadata = detail_codes.get(
                detail_code,
                {},
            )
            term_collection_totals.append(
                TermDetailCodeTotal(
                    fiscal_year=fiscal_year,
                    term=term,
                    detail_code=detail_code,
                    description=_clean_text(
                        metadata.get(
                            "detail_code_description"
                        )
                    ),
                    code_type=_clean_text(
                        metadata.get("type")
                    ).upper(),
                    category=_clean_text(
                        metadata.get("category")
                    ).upper(),
                    transaction_count=(
                        accumulator.transaction_count
                    ),
                    student_count=len(
                        accumulator.student_ids
                    ),
                    total_amount=(
                        accumulator.total_amount
                    ),
                )
            )

    return TrendsFileAnalysisResult(
        fiscal_year=analysis,
        detail_codes=sorted(
            detail_totals.values(),
            key=lambda item: item.detail_code,
        ),
        group_averages=group_averages,
        category_averages=category_averages,
        term_groups=term_group_totals,
        term_collections=term_collection_totals,
    )

def build_reporting_group_totals(
    *,
    fiscal_year_results: list[
        FiscalYearAnalysis
    ],
    detail_code_results: list[
        DetailCodeTotal
    ],
    group_average_results: list[
        ChargeAverage
    ],
) -> list[ReportingGroupTotal]:
    """
    Build annual category-group and exact-code totals.

    Tuition, Room and Board, and Fees come from configured
    Banner categories. WOFF and BDRC use exact detail codes.
    """
    group_results_by_year: dict[
        int,
        list[ChargeAverage],
    ] = defaultdict(list)

    for result in group_average_results:
        group_results_by_year[
            result.fiscal_year
        ].append(result)

    detail_results_by_year_and_code = {
        (
            result.fiscal_year,
            result.detail_code.upper(),
        ): result
        for result in detail_code_results
    }

    reporting_totals: list[
        ReportingGroupTotal
    ] = []

    for fiscal_year_result in fiscal_year_results:
        fiscal_year = (
            fiscal_year_result.fiscal_year
        )

        for group_result in group_results_by_year[
            fiscal_year
        ]:
            reporting_totals.append(
                ReportingGroupTotal(
                    fiscal_year=fiscal_year,
                    label=group_result.label,
                    included_codes=(
                        group_result.category_codes
                    ),
                    transaction_count=(
                        group_result.transaction_count
                    ),
                    charge_transaction_count=(
                        group_result
                        .charge_transaction_count
                    ),
                    payment_credit_transaction_count=(
                        group_result
                        .payment_credit_transaction_count
                    ),
                    student_count_with_activity=(
                        group_result
                        .student_count_with_activity
                    ),
                    all_student_count=(
                        group_result.all_student_count
                    ),
                    charge_amount=(
                        group_result.charge_amount
                    ),
                    payment_credit_amount=(
                        group_result
                        .payment_credit_amount
                    ),
                    net_amount=(
                        group_result.net_category_amount
                    ),
                )
            )

        for (
            reporting_label,
            detail_code,
        ) in ANNUAL_EXACT_REPORTING_GROUPS:
            detail_result = (
                detail_results_by_year_and_code.get(
                    (
                        fiscal_year,
                        detail_code,
                    )
                )
            )

            if detail_result is None:
                transaction_count = 0
                student_count = 0
                charge_transaction_count = 0
                payment_transaction_count = 0
                charge_amount = 0.0
                payment_amount = 0.0
                net_amount = 0.0
            else:
                code_type = (
                    detail_result.code_type.upper()
                )
                is_charge = code_type == "C"
                is_payment = code_type == "P"

                transaction_count = (
                    detail_result.transaction_count
                )
                student_count = (
                    detail_result.student_count
                )

                charge_transaction_count = (
                    transaction_count
                    if is_charge
                    else 0
                )
                payment_transaction_count = (
                    transaction_count
                    if is_payment
                    else 0
                )

                charge_amount = (
                    detail_result.total_amount
                    if is_charge
                    else 0.0
                )
                payment_amount = (
                    detail_result.total_amount
                    if is_payment
                    else 0.0
                )
                net_amount = (
                    detail_result.signed_ar_effect
                )

            reporting_totals.append(
                ReportingGroupTotal(
                    fiscal_year=fiscal_year,
                    label=reporting_label,
                    included_codes=(
                        f"Detail Code: {detail_code}"
                    ),
                    transaction_count=(
                        transaction_count
                    ),
                    charge_transaction_count=(
                        charge_transaction_count
                    ),
                    payment_credit_transaction_count=(
                        payment_transaction_count
                    ),
                    student_count_with_activity=(
                        student_count
                    ),
                    all_student_count=(
                        fiscal_year_result.student_count
                    ),
                    charge_amount=charge_amount,
                    payment_credit_amount=(
                        payment_amount
                    ),
                    net_amount=net_amount,
                )
            )

    return reporting_totals

def analyze_all_files(
    files: list[Path],
    *,
    detail_codes: dict[str, dict[str, object]],
    config: TrendsConfig,
) -> TrendsAnalysisResult:
    fiscal_year_results: list[
        FiscalYearAnalysis
    ] = []
    detail_code_results: list[
        DetailCodeTotal
    ] = []
    group_average_results: list[
        ChargeAverage
    ] = []
    category_average_results: list[
        ChargeAverage
    ] = []
    term_group_total_results: list[
        TermGroupTotal
    ] = []
    term_collection_total_results: list[
        TermDetailCodeTotal
    ] = []

    for path in files:
        print(
            f"Analyzing {path.name}...",
            flush=True,
        )

        file_result = analyze_tgiaccd_file(
            path,
            detail_codes=detail_codes,
            config=config,
        )

        fiscal_year_results.append(
            file_result.fiscal_year
        )
        detail_code_results.extend(
            file_result.detail_codes
        )
        group_average_results.extend(
            file_result.group_averages
        )
        category_average_results.extend(
            file_result.category_averages
        )
        term_group_total_results.extend(
            file_result.term_groups
        )
        term_collection_total_results.extend(
            file_result.term_collections
        )

    return TrendsAnalysisResult(
        fiscal_years=fiscal_year_results,
        detail_codes=detail_code_results,
        group_averages=group_average_results,
        category_averages=category_average_results,
        term_groups=term_group_total_results,
        term_collections=term_collection_total_results,
    )
