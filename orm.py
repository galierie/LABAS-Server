from sqlmodel import Field, SQLModel

class Voter(SQLModel, table=True):
  __tablename__ = "voters"
  uin: int = Field(primary_key=True)
  precinct: str
  voted: bool
