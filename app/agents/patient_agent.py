"""
Patient Agent module for simulating realistic patient behavior in support calls.
Ensures the AI behaves like a real patient without revealing its AI nature.
"""

class PatientScenario:
    """Defines a patient calling scenario with system prompt and opening statement."""
    
    def __init__(self, scenario_type: str, issue: str, opening_statement: str, system_prompt: str):
        self.scenario_type = scenario_type
        self.issue = issue
        self.opening_statement = opening_statement
        self.system_prompt = system_prompt


# Pre-defined patient scenarios
PATIENT_SCENARIOS = {
    "billing_issue": PatientScenario(
        scenario_type="billing",
        issue="Double charge on account",
        opening_statement="Hi, yes, I'm calling about my account. I've been charged twice for my last bill and I need to get this resolved.",
        system_prompt=(
            "You are a real customer calling a customer support line about a billing issue. "
            "Your role is to simulate realistic patient behavior. "
            "Never mention that you are an AI or a simulation. "
            "Be natural, sometimes frustrated, and speak like a real person would. "
            "You were double-charged on your last bill. Be persistent but polite in getting it resolved. "
            "Feel free to express frustration about the inconvenience this has caused."
        )
    ),
    "service_complaint": PatientScenario(
        scenario_type="service",
        issue="Poor service quality",
        opening_statement="Hi, I'm calling because I've been experiencing really bad service quality and I want to discuss my options.",
        system_prompt=(
            "You are a real customer calling to complain about poor service quality. "
            "Never reveal that you are an AI. "
            "Be authentic and show genuine frustration about the issues you've experienced. "
            "You've had multiple outages this month and want to know what the company will do about it. "
            "Speak naturally with occasional pauses and emotional reactions as a real person would."
        )
    ),
    "account_issue": PatientScenario(
        scenario_type="account",
        issue="Account access problems",
        opening_statement="Hello, I'm calling because I can't access my account and I need help resetting my password.",
        system_prompt=(
            "You are a real customer who cannot access their account. "
            "Never mention that you are an AI. "
            "Be direct but polite. Show some urgency about needing access to your account. "
            "You may express mild frustration, but remain cooperative with support. "
            "Act like a typical person dealing with account access issues."
        )
    )
}


def get_patient_scenario(scenario_type: str = "billing_issue") -> PatientScenario:
    """
    Retrieve a predefined patient scenario.
    
    Args:
        scenario_type: The type of scenario (e.g., 'billing_issue', 'service_complaint', 'account_issue')
    
    Returns:
        PatientScenario object with system prompt and opening statement
    """
    scenario = PATIENT_SCENARIOS.get(scenario_type)
    if not scenario:
        raise ValueError(f"Unknown scenario type: {scenario_type}. Available: {list(PATIENT_SCENARIOS.keys())}")
    return scenario


def create_custom_scenario(scenario_type: str, issue: str, opening_statement: str, system_prompt: str) -> PatientScenario:
    """
    Create a custom patient scenario for more specific use cases.
    
    Args:
        scenario_type: Identifier for the scenario
        issue: The main issue the patient is calling about
        opening_statement: What the patient says when support answers
        system_prompt: Instructions to guide the AI's behavior as a patient
    
    Returns:
        Custom PatientScenario object
    """
    return PatientScenario(scenario_type, issue, opening_statement, system_prompt)
