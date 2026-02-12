# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""
RAGAS evaluator integration for OpenViking.
"""

import asyncio
from typing import Any, Dict, List, Optional

from openviking.eval.base import BaseEvaluator
from openviking.eval.types import EvalDataset, EvalResult, EvalSample, SummaryResult
from openviking_cli.utils.logger import get_logger

logger = get_logger(__name__)


class RagasEvaluator(BaseEvaluator):
    """
    Evaluator using the RAGAS framework.

    Requires 'ragas' and 'datasets' packages.
    """

    def __init__(
        self,
        metrics: Optional[List[Any]] = None,
        llm: Optional[Any] = None,
        embeddings: Optional[Any] = None,
    ):
        """
        Initialize Ragas evaluator.

        Args:
            metrics: List of Ragas metrics (e.g., faithfulness, answer_relevance).
                    If None, uses a default set.
            llm: LLM to use for evaluation (LangChain base LLM).
            embeddings: Embeddings to use for evaluation (LangChain base embeddings).
        """
        try:
            from ragas import metrics as ragas_metrics
            from ragas.metrics import (
                answer_relevance,
                context_precision,
                context_recall,
                faithfulness,
            )
        except ImportError:
            raise ImportError(
                "RAGAS evaluation requires 'ragas' package. "
                "Install it with: pip install ragas datasets"
            )

        self.metrics = metrics or [
            faithfulness,
            answer_relevance,
            context_precision,
            context_recall,
        ]
        self.llm = llm
        self.embeddings = embeddings

    async def evaluate_sample(self, sample: EvalSample) -> EvalResult:
        """Evaluate a single sample using Ragas."""
        # Ragas is optimized for batch evaluation, so we wrap it in a dataset
        dataset = EvalDataset(samples=[sample])
        summary = await self.evaluate_dataset(dataset)
        return summary.results[0]

    async def evaluate_dataset(self, dataset: EvalDataset) -> SummaryResult:
        """Evaluate a dataset using Ragas."""
        try:
            from datasets import Dataset
            from ragas import evaluate
        except ImportError:
            raise ImportError(
                "RAGAS evaluation requires 'datasets' package. "
                "Install it with: pip install datasets"
            )

        # Prepare Ragas compatible dataset
        data = {
            "question": [s.query for s in dataset.samples],
            "contexts": [s.context for s in dataset.samples],
            "answer": [s.response or "" for s in dataset.samples],
            "ground_truth": [s.ground_truth or "" for s in dataset.samples],
        }

        ragas_dataset = Dataset.from_dict(data)

        # Run Ragas evaluation
        # Ragas evaluation is typically synchronous or uses its own async loop
        # We run it in a thread if it's blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: evaluate(
                ragas_dataset,
                metrics=self.metrics,
                llm=self.llm,
                embeddings=self.embeddings,
            ),
        )

        # Convert Ragas result back to OpenViking types
        eval_results = []
        df = result.to_pandas()

        for i, sample in enumerate(dataset.samples):
            scores = {}
            for metric in self.metrics:
                metric_name = metric.name
                if metric_name in df.columns:
                    scores[metric_name] = float(df.iloc[i][metric_name])

            eval_results.append(
                EvalResult(
                    sample=sample,
                    scores=scores
                )
            )

        return SummaryResult(
            dataset_name=dataset.name,
            sample_count=len(dataset.samples),
            mean_scores=dict(result),
            results=eval_results,
        )
