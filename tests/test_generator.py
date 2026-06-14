import pytest
from unittest.mock import patch, MagicMock
from ai.guide_generator import generate_team_report, generate_efficiency_guide

@patch("ai.guide_generator.model")
def test_generate_team_report_success(mock_model):
    """Test that the team report generator returns the expected text when the API succeeds."""
    # Setup mock
    mock_response = MagicMock()
    mock_response.text = "This is a mocked AI summary for the team."
    mock_model.generate_content.return_value = mock_response
    
    # Execute
    team_data = {
        "average_score": 60.5,
        "total_spend": 150.0,
        "critical_count": 2
    }
    result = generate_team_report(team_data)
    
    # Assert
    assert result == "This is a mocked AI summary for the team."
    mock_model.generate_content.assert_called_once()

@patch("ai.guide_generator.model")
def test_generate_efficiency_guide_success(mock_model):
    """Test that the guide generator returns the expected parsed list."""
    # Setup mock
    mock_response = MagicMock()
    # Mock a numbered list response
    mock_response.text = "Here is your guide:\n1. Use compact more\n2. Cache large files"
    mock_model.generate_content.return_value = mock_response
    
    # Execute
    user_data = {
        "efficiency_score": 45.0,
        "cache_ratio": 0.2,
        "opus_pct": 0.8
    }
    result = generate_efficiency_guide(user_data, "critical")
    
    # Assert
    assert len(result) == 2
    assert result[0]["desc"] == "Use compact more"
    assert result[1]["desc"] == "Cache large files"
    mock_model.generate_content.assert_called_once()

@patch("ai.guide_generator.model")
def test_generate_team_report_fallback_on_error(mock_model):
    """Test that the fallback logic kicks in if the API raises an exception."""
    # Setup mock to raise an exception
    mock_model.generate_content.side_effect = Exception("API rate limit exceeded")
    
    # Execute
    team_data = {
        "average_score": 60.5,
        "total_spend": 150.0,
        "critical_count": 2
    }
    result = generate_team_report(team_data)
    
    # Assert
    assert "System Offline" in result
