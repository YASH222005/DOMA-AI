from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./doma_ai.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    coins = Column(Integer, default=5)  # 5 free trial credits on signup
    is_unlimited = Column(Boolean, default=False)
    subscription_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tickets = relationship("SupportTicket", back_populates="owner")

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subject = Column(String, nullable=False)
    message = Column(String, nullable=False)
    status = Column(String, default="Open")
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="tickets")

def init_db():
    Base.metadata.create_all(bind=engine)