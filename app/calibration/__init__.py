"""Transparent calibration reports for Prediction Arena agents."""

from app.calibration.agent_performance_tracker import (
    AgentPerformanceReport,
    build_agent_performance_reports,
    run_prediction_calibration,
)
from app.calibration.prediction_target_calibration import (
    PredictionTargetCalibrationReport,
    analyze_prediction_target_calibration,
    prediction_target_issues,
)
from app.calibration.scoreline_calibration import (
    ScorelineBiasReport,
    analyze_scoreline_calibration,
)
from app.calibration.upset_calibration import (
    UpsetBiasReport,
    analyze_upset_calibration,
    score_underdog_path_quality,
)

__all__ = [
    "AgentPerformanceReport",
    "PredictionTargetCalibrationReport",
    "ScorelineBiasReport",
    "UpsetBiasReport",
    "analyze_prediction_target_calibration",
    "analyze_scoreline_calibration",
    "analyze_upset_calibration",
    "build_agent_performance_reports",
    "prediction_target_issues",
    "run_prediction_calibration",
    "score_underdog_path_quality",
]
