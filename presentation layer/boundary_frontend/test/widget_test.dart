import 'package:flutter_test/flutter_test.dart';

import 'package:boundary_frontend/main.dart';

void main() {
  testWidgets('Boundary dashboard renders', (WidgetTester tester) async {
    await tester.pumpWidget(const BoundaryApp());
    expect(find.byType(BoundaryDashboard), findsOneWidget);
  });
}
