"""Authentication service."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.orm import MemberModel
from template.adapters.repositories import MemberRepository
from template.domain.models.member import Member
from template.domain.schemas.member import MemberCreate, MemberUpdate, TokenData

# Configuration
SECRET_KEY = "your-secret-key"  # Change this to a secure secret key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")


class AuthService:
    def __init__(self, db: Session):
        """Initialize the AuthService with a database session."""
        self.db = db
        self.member_repository = MemberRepository(db)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain text password against a hashed password."""
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        """Get the hashed password."""
        return pwd_context.hash(password)

    def get_member_by_email(self, email: str) -> Optional[Member]:
        """Get a member by their email address."""
        db_member = self.member_repository.get_member_by_email(email)
        return db_member

    def update_member_password(self, member: Member, password: str) -> Member:
        """Update a member's password."""
        # Get the ORM model
        db_member = self.db.query(MemberModel).filter(MemberModel.id == member.id).first()
        if not db_member:
            raise HTTPException(status_code=404, detail="Member not found")

        # Update the password
        db_member.hashed_password = self.get_password_hash(password)
        self.db.commit()

        # Return domain model
        return Member(
            id=db_member.id,
            name=db_member.name,
            telephone=db_member.telephone,
            email=db_member.email,
            hashed_password=db_member.hashed_password,
        )

    def update_member(self, member: Member, update_data: MemberUpdate) -> Member:
        """Update member information."""
        # Get the ORM model
        db_member = self.db.query(MemberModel).filter(MemberModel.id == member.id).first()
        if not db_member:
            raise HTTPException(status_code=404, detail="Member not found")

        # Update the member information
        if update_data.name is not None:
            db_member.name = update_data.name
        if update_data.telephone is not None:
            db_member.telephone = update_data.telephone
        if update_data.email is not None:
            # Check if email is already taken by another member
            existing = self.get_member_by_email(update_data.email)
            if existing and existing.id != member.id:
                raise ValueError("Email already registered")
            db_member.email = update_data.email

        self.db.commit()

        # Return domain model
        return Member(
            id=db_member.id,
            name=db_member.name,
            telephone=db_member.telephone,
            email=db_member.email,
            hashed_password=db_member.hashed_password,
        )

    def create_member(self, member: MemberCreate) -> Member:
        """Create a new member."""
        db_member = MemberModel(
            email=member.email,
            name=member.name,
            telephone=member.telephone,
            hashed_password=self.get_password_hash(member.password),
        )
        self.db.add(db_member)
        self.db.commit()
        self.db.refresh(db_member)

        # Return domain model
        return Member(
            id=db_member.id,
            name=db_member.name,
            telephone=db_member.telephone,
            email=db_member.email,
            hashed_password=db_member.hashed_password,
        )

    def authenticate_member(self, email: str, password: str) -> Optional[Member]:
        """Authenticate a member by their email and password."""
        member = self.get_member_by_email(email)
        if not member or not member.hashed_password:
            return None
        if not self.verify_password(password, member.hashed_password):
            return None
        return member

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create an access token."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt


async def get_current_member(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Member:
    """Get the current member."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError as exc:
        raise credentials_exception from exc

    auth_service = AuthService(db)
    member = auth_service.get_member_by_email(email=token_data.email)
    if member is None:
        raise credentials_exception
    return member


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """Get the authentication service."""
    return AuthService(db)
