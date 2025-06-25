from typing import Optional, Union

from butty.compat import AnnotationCompat


def test_annotation():
    assert AnnotationCompat(int).core_type is int
    assert AnnotationCompat(int).outer_type is None
    assert not AnnotationCompat(int).optional

    assert AnnotationCompat(int | None).core_type is int
    assert AnnotationCompat(int | None).outer_type is None
    assert AnnotationCompat(int | None).optional

    assert AnnotationCompat(Optional[int]).core_type is int
    assert AnnotationCompat(Optional[int]).outer_type is None
    assert AnnotationCompat(Optional[int]).optional

    assert AnnotationCompat(Union[int, None]).core_type is int
    assert AnnotationCompat(Union[int, None]).outer_type is None
    assert AnnotationCompat(Union[int, None]).optional

    assert AnnotationCompat(list[int]).core_type is int
    assert AnnotationCompat(list[int]).outer_type is list
    assert not AnnotationCompat(list[int]).optional

    assert AnnotationCompat(list[int | None]).core_type is int
    assert AnnotationCompat(list[int | None]).outer_type is list
    assert not AnnotationCompat(list[int | None]).optional

    assert AnnotationCompat(list[int] | None).core_type is int
    assert AnnotationCompat(list[int] | None).outer_type is list
    assert AnnotationCompat(list[int] | None).optional

    assert AnnotationCompat(list[int | None] | None).core_type is int
    assert AnnotationCompat(list[int | None] | None).outer_type is list
    assert AnnotationCompat(list[int | None] | None).optional

    assert AnnotationCompat(dict[str, int]).core_type is int
    assert AnnotationCompat(dict[str, int]).outer_type is dict
    assert not AnnotationCompat(dict[str, int]).optional

    assert AnnotationCompat(dict[str, int | None]).core_type is int
    assert AnnotationCompat(dict[str, int | None]).outer_type is dict
    assert not AnnotationCompat(dict[str, int | None]).optional

    assert AnnotationCompat(dict[str, int] | None).core_type is int
    assert AnnotationCompat(dict[str, int] | None).outer_type is dict
    assert AnnotationCompat(dict[str, int] | None).optional

    assert AnnotationCompat(dict[str, int | None] | None).core_type is int
    assert AnnotationCompat(dict[str, int | None] | None).outer_type is dict
    assert AnnotationCompat(dict[str, int | None] | None).optional

    assert AnnotationCompat(None).core_type is None
    assert AnnotationCompat(None).outer_type is None
    assert not AnnotationCompat(None).optional
