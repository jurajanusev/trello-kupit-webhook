from __future__ import annotations


def resolve_target_list_id(
    card_info,
    board_config,
    board_target_lists,
    get_board_short_link,
    get_list_board_id,
):
    """Resolve a target without ever crossing the source card's board.

    A same-board environment override remains supported.  A stale or invalid
    cross-board override is ignored and the built-in target for the supported
    source board is used only after its ownership is verified as well.
    """
    source_board_id = card_info.get("idBoard")
    if not source_board_id:
        return None

    board_short_link = get_board_short_link(source_board_id)
    default_target = board_target_lists.get(board_short_link)
    if not default_target:
        return None

    configured = board_config.get(card_info.get("idList"), {})
    configured_target = configured.get("target_list_id")
    candidates = []
    if configured_target:
        candidates.append(configured_target)
    if default_target not in candidates:
        candidates.append(default_target)

    for target_list_id in candidates:
        if get_list_board_id(target_list_id) == source_board_id:
            return target_list_id
    return None
