from dataclasses import dataclass, field


@dataclass
class USComment:
    comment_id: str
    story_id: str
    text: str
    round_number: int = 0


@dataclass
class CommentAdjustment:
    story_id: str
    original_text: str
    adjustment_instructions: str
    round_number: int


def attach_comment_to_story(story_id: str, text: str, round_number: int = 0) -> USComment:
    import uuid
    return USComment(
        comment_id=str(uuid.uuid4())[:8],
        story_id=story_id,
        text=text,
        round_number=round_number,
    )


def process_comment_as_adjustment(comment: USComment, story_content: str) -> CommentAdjustment:
    return CommentAdjustment(
        story_id=comment.story_id,
        original_text=story_content,
        adjustment_instructions=comment.text,
        round_number=comment.round_number + 1,
    )
