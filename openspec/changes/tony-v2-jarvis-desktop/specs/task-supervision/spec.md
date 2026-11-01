# Spec Delta

## ADDED Requirements

### Requirement: User cancellation
A running task SHALL be cancellable by the user from the interface; it SHALL then be cancelled as any other cancelled task, with the reason `tarea cancelada por el usuario`, and a pending confirmation of that task SHALL be answered as not confirmed.

#### Scenario: Cancelled while waiting for confirmation
- **WHEN** a task is waiting for the confirmation of `filesystem.delete_file` and the user cancels
- **THEN** the tool is not executed, the task log ends with `task_finished` outcome `cancelled` and `errores` contains `tarea cancelada por el usuario`
