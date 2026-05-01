"""
Define db models based on the created schema
"""

from sqlmodel import Field, SQLModel
from typing import Optional

class Voter(SQLModel, table=True):
    __tablename__ = "voters"
    uin: int = Field(primary_key=True)
    precinct: str
    voted: bool

class Scope(SQLModel, table=True):
    scope_id: int = Field(primary_key=True)
    scope_name: str

class Position(SQLModel, table=True):
    position_id: int = Field(primary_key=True)
    position_name: str
    scope_id: int = Field(foreign_key="scope.scope_id")
    max_votes: int = Field(default=1)

class Province(SQLModel, table=True):
    __tablename__ = "provinces"
    province_id: str = Field(primary_key=True)
    province_name: str

class City(SQLModel, table=True):
    __tablename__ = "cities"
    city_id: str = Field(primary_key=True)
    city_name: str
    province_id: str = Field(foreign_key="provinces.province_id")

class Candidate(SQLModel, table=True):
    __tablename__ = "candidates"
    candidate_id: int = Field(primary_key=True)
    # Name and position determines candidate number
    first_name: str
    last_name: str
    middle_name: str
    party: str | None = None
    position_id: int = Field(foreign_key="position.position_id")
    province_id: Optional[str] = Field(default=None, foreign_key="provinces.province_id")
    city_id: Optional[str] = Field(default=None, foreign_key="cities.city_id")

class Bubble_Coordinate(SQLModel, table=True):
    __tablename__ = "bubble_coordinates"
    bubble_id: int = Field(primary_key=True)
    uin: str = Field(foreign_key="voters.uin")
    candidate_id: int = Field(foreign_key="candidates.candidate_id")
    bubble_x_pt: float = Field(nullable=False)
    bubble_y_pt: float = Field(nullable=False)
    page: int = Field(nullable=False)
