// First screen of the React + Astryx UI. It sits beside the existing screens and is loaded
// only when opened, so the always-on widget pays nothing for it at start-up.
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import type { LinkStatus } from "../types";
import { aboutRows } from "./about-model";

export interface AboutScreenProps {
  readonly version: string;
  readonly link: LinkStatus;
  readonly onBack: () => void;
}

export function AboutScreen({ version, link, onBack }: AboutScreenProps) {
  return (
    <VStack gap={4} padding={4}>
      <Heading level={1}>À propos d’Omniscient</Heading>
      <dl>
        {aboutRows(version, link).map((row) => (
          <VStack key={row.label} gap={0.5}>
            <Text as="div" type="supporting">
              <dt>{row.label}</dt>
            </Text>
            <Text as="div">
              <dd>{row.value}</dd>
            </Text>
          </VStack>
        ))}
      </dl>
      <Button label="Retour" variant="secondary" onClick={onBack} />
    </VStack>
  );
}
