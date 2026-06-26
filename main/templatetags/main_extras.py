from django import template
 
register = template.Library()
 
DEPOSIT_BADGE_CLASSES = {
    "paid": "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    "due": "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    "overdue": "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400",
}
 
TRANSPORT_TEXT_CLASSES = {
    "confirmed": "text-green-600 dark:text-green-400",
    "pending": "text-gray-500 dark:text-gray-400",
    "overdue": "text-red-500 dark:text-red-400",
}
 
REMINDER_BADGE_CLASS = (
    "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400"
)
 
 
@register.filter
def deposit_badge_class(token):
    """token: 'paid' | 'due' | 'overdue'"""
    return DEPOSIT_BADGE_CLASSES.get(token, DEPOSIT_BADGE_CLASSES["due"])
 
 
@register.filter
def transport_text_class(token):
    """token: 'confirmed' | 'pending' | 'overdue'"""
    return TRANSPORT_TEXT_CLASSES.get(token, TRANSPORT_TEXT_CLASSES["pending"])
 
