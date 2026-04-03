# Contributing to MCP Server Template

Thank you for your interest in contributing to the MCP Server Template! We welcome contributions from the community and are grateful for any help you can provide.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/your-username/mcp-server-template.git
   cd mcp-server-template
   ```
3. Create a new branch for your feature or bug fix:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

1. Ensure you have Python 3.10+ installed
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the package in development mode:
   ```bash
   pip install -e .
   ```
4. Install development dependencies:
   ```bash
   pip install pytest pytest-asyncio pytest-cov ruff mypy
   ```

## Making Changes

### Code Style

- Follow PEP 8 guidelines
- Use type hints for all function signatures
- Keep line length to 88 characters (Black default)
- Use descriptive variable and function names

### Testing

- Write tests for any new functionality
- Ensure all existing tests pass:
  ```bash
  pytest
  ```
- Aim for at least 80% test coverage:
  ```bash
  pytest --cov=src --cov-report=html
  ```

### Linting

Before submitting, ensure your code passes linting:
```bash
ruff check .
mypy src/
```

## Submitting Changes

1. Commit your changes with clear, descriptive commit messages:
   ```bash
   git commit -m "feat: add new prompt management feature"
   ```
   
   Use conventional commit format:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `docs:` for documentation changes
   - `test:` for test additions/changes
   - `chore:` for maintenance tasks

2. Push your branch to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

3. Open a Pull Request on GitHub with:
   - Clear description of the changes
   - Reference to any related issues
   - Screenshots/examples if applicable

## Pull Request Guidelines

- Keep PRs focused on a single feature or fix
- Update documentation as needed
- Add tests for new functionality
- Ensure CI checks pass
- Be responsive to feedback and review comments

## Areas for Contribution

We especially welcome contributions in these areas:

- **New MCP Tools**: Add useful tools that extend server capabilities
- **Prompt Templates**: Contribute effective prompt templates for various use cases
- **Documentation**: Improve setup guides, API documentation, or examples
- **Testing**: Increase test coverage or add integration tests
- **Performance**: Optimize server performance or resource usage
- **Container Support**: Enhance Containerfile or OpenShift deployment manifests

## Reporting Issues

When reporting issues, please include:

- Python version
- Operating system
- Steps to reproduce the issue
- Expected vs actual behavior
- Any relevant error messages or logs

## Questions?

If you have questions about contributing, feel free to:
- Open a GitHub issue for discussion
- Check existing issues and pull requests
- Review the project documentation

## Code of Conduct

Please note that this project follows a standard Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to wjackson@redhat.com.

## License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.