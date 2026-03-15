from aiogram.fsm.state import State, StatesGroup


class BotStates(StatesGroup):
    onboarding_full_name = State()
    onboarding_group = State()
    onboarding_program = State()
    profile_edit_full_name = State()
    profile_edit_group = State()
    waiting_source_url = State()
    waiting_formula_input = State()
    confirm_source = State()
    analysis_running = State()
    clarify_student_match = State()
    clarify_grading_scheme = State()
    clarify_deadline = State()
