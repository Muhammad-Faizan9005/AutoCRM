from app.repositories.base import BaseRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.deal_repository import DealRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.note_repository import NoteRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "CustomerRepository",
    "DealRepository",
    "LeadRepository",
    "MessageRepository",
    "NoteRepository",
    "OrganizationRepository",
    "TaskRepository",
    "TicketRepository",
    "UserRepository",
]
