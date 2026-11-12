from __future__ import annotations

from jira_sprint_report.infrastructure.config import PROMPTS_DIR


def default_prompt() -> str:
    prompt_file = PROMPTS_DIR / "sprint_report.txt"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8").strip()
    return (
        "Liste todas as tarefas da sprint atual com pedido e solução/comentários. "
        "Não invente informações."
    )


def build_prompt(
    base_prompt: str | None = None,
    renegotiations: str = "",
    mid_sprint: str = "",
    board_name: str = "",
) -> str:
    """Compose the Rovo prompt with board scope and mid-sprint / renegotiation notes."""
    prompt = (base_prompt or default_prompt()).strip()
    board = (board_name or "").strip()
    mid = (mid_sprint or "").strip()
    reno = (renegotiations or "").strip()

    if board:
        prompt = (
            f"Board selecionado pelo usuário (obrigatório): {board}.\n"
            "Use somente a sprint ativa deste board. Não misture tasks de outros boards.\n\n"
            f"{prompt}"
        )

    prompt += "\n\n---\nNotas do usuário para classificação do escopo:\n"

    if mid:
        prompt += (
            "\nTasks que ENTRARAM após o início da sprint (lista oficial do usuário). "
            "Coloque-as na seção 'Entraram após o início'. "
            "Pode enriquecer com título/detalhe do Jira, sem inventar fatos:\n\n"
            f"{mid}\n"
        )
    else:
        prompt += (
            "\nEntraram após o início: o usuário não passou lista. "
            "Tente identificar pelo Jira; se não tiver certeza, não invente.\n"
        )

    if reno:
        prompt += (
            "\nRenegociações / tasks REMOVIDAS da sprint (lista oficial do usuário + motivo). "
            "Coloque-as na seção 'Renegociações', uma por task, usando o motivo informado "
            "(pode reescrever de forma clara, sem inventar):\n\n"
            f"{reno}\n"
        )
    else:
        prompt += (
            "\nRenegociações: nenhuma informada. Não invente tasks removidas; "
            "omita a seção Renegociações.\n"
        )

    return prompt
